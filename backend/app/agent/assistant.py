"""The chat's tool-calling assistant: our agent as an MCP CLIENT of our own MCP server (Phase 4b, M10).

The other branches of the chat graph are fixed: the router picks one, and it runs. Open requests
("what should I study today?") need several lookups in an order only the model can decide, so this
branch is a small ReAct loop:

    ask the model (with the tool list) ─▶ it asks for tool calls ─▶ run them ─▶ add the results ─┐
          ▲                                                                                      │
          └──────────────────────────────── until it answers, or MCP_AGENT_MAX_STEPS ◀───────────┘

The tools come from our MCP server (app/mcp_server/server.py) through `langchain-mcp-adapters`, over
an in-memory MCP connection: the same tool code, permission checks, rate limit and audit log as
Claude Desktop gets over HTTP. Optionally (MCP_NOTES_DIR), it also gets read-only tools of an
EXTERNAL MCP server, the official filesystem server, to read a folder of your own notes (M12).

The loop is written out (instead of langchain's create_agent) so every step is visible: each model
call goes through our LLM gateway (budget, retries, cost row, trace) and each tool call is shown in
the chat.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.service import chat_with_tools
from app.mcp_server.server import local_identity, mcp
from app.mcp_server.tokens import Identity
from app.models import User
from app.prompts.assistant import ASSISTANT_FINISH, ASSISTANT_SYSTEM

log = logging.getLogger("app.agent")

# Least privilege: the chat assistant gets only the tools it needs (no ask_doubt: it would be an AI
# call inside an AI call; no list_students: the chat is the student portal).
LMS_TOOLS = {"search_course_material", "get_learning_path", "my_weak_topics", "practice_questions"}
NOTES_TOOLS = {"read_text_file", "list_directory", "search_files"}  # read-only subset of the filesystem server


@dataclass
class ToolStep:
    name: str
    args: dict
    ok: bool
    summary: str
    structured: dict | None = None


@dataclass
class AssistantRun:
    answer: str
    steps: list[ToolStep] = field(default_factory=list)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    notes_error: str | None = None


@asynccontextmanager
async def mcp_tools(user: User) -> AsyncIterator[tuple[list[BaseTool], str | None]]:
    """Connect to our MCP server (in memory, as `user`) and, if configured, to the notes server.
    Yields (tools, why the notes server is unavailable)."""
    async with AsyncExitStack() as stack:
        token = local_identity.set(Identity(user=user, via="agent"))
        stack.callback(local_identity.reset, token)
        # The server side of this connection runs in a task started here, so it inherits `local_identity`.
        lms = await stack.enter_async_context(create_connected_server_and_client_session(mcp))
        tools = [t for t in await load_mcp_tools(lms) if t.name in LMS_TOOLS]
        notes_error = None
        if folder := get_settings().mcp_notes_dir:
            try:
                tools += await _notes_tools(stack, folder)
            except Exception as exc:  # noqa: BLE001 - notes are optional: answer without them
                notes_error = f"Notes folder unavailable: {type(exc).__name__}"
                log.warning("Could not start the notes MCP server: %s", exc)
        yield tools, notes_error


async def _notes_tools(stack: AsyncExitStack, folder: str) -> list[BaseTool]:
    """The official filesystem MCP server, launched over stdio (needs Node). It can only see `folder`."""
    params = StdioServerParameters(command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", folder])
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return [t for t in await load_mcp_tools(session) if t.name in NOTES_TOOLS]


def _first(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _summary(content) -> str:
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    return text[:200]


async def _call(tool: BaseTool | None, call: dict) -> tuple[ToolMessage, ToolStep]:
    if tool is None:
        msg = ToolMessage(f"Unknown tool {call['name']}.", name=call["name"], tool_call_id=call["id"], status="error")
        return msg, ToolStep(call["name"], call["args"], False, "unknown tool")
    try:
        msg = await tool.ainvoke({**call, "type": "tool_call"})
    except Exception as exc:  # noqa: BLE001 - a failed tool is information for the model, not a crash
        msg = ToolMessage(f"Error: {exc}", name=call["name"], tool_call_id=call["id"], status="error")
    ok = getattr(msg, "status", "success") != "error"
    artifact = getattr(msg, "artifact", None)
    structured = artifact.get("structured_content") if isinstance(artifact, dict) else None
    return msg, ToolStep(call["name"], call["args"], ok, _summary(msg.content), structured)


async def run(session: AsyncSession, user: User, question: str, on_step=None) -> AssistantRun:
    """The loop. `on_step(ToolStep)` is called after each tool call (the chat shows it live)."""
    max_steps = get_settings().mcp_agent_max_steps
    out = AssistantRun(answer="")
    messages: list[BaseMessage] = [
        SystemMessage(ASSISTANT_SYSTEM.format(name=user.full_name, role=user.role.value, max_steps=max_steps)),
        HumanMessage(question),
    ]
    try:
        async with mcp_tools(user) as (tools, out.notes_error):
            by_name = {t.name: t for t in tools}
            for step in range(max_steps + 1):
                last = step == max_steps
                if last:
                    messages.append(HumanMessage(ASSISTANT_FINISH))
                ai, result = await chat_with_tools(
                    session,
                    messages=messages,
                    tools=tools,
                    feature="assistant",
                    user=user,
                    tool_choice="none" if last else None,
                )
                out.llm_calls += 1
                out.input_tokens += result.input_tokens
                out.output_tokens += result.output_tokens
                out.cost_usd += result.cost_usd
                messages.append(ai)
                if not ai.tool_calls:
                    out.answer = result.text
                    return out
                for call in ai.tool_calls:
                    msg, tool_step = await _call(by_name.get(call["name"]), call)
                    messages.append(msg)
                    out.steps.append(tool_step)
                    if on_step:
                        on_step(tool_step)
    except BaseExceptionGroup as group:
        # The MCP connection runs in a task group, which wraps errors (e.g. "daily budget used up")
        # in an ExceptionGroup. Unwrap it, so the chat reports the real error.
        raise _first(group) from None
    out.answer = "I couldn't finish this within my step limit. Try asking for one thing at a time."
    return out
