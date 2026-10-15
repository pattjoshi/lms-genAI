"""Phase 4b: the MCP server's guard rails and the chat assistant's tool loop. No LLM, no database."""

from contextlib import asynccontextmanager

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from mcp.server.fastmcp.exceptions import ToolError

from app.agent import assistant
from app.agent.graph import tool_card
from app.agent.intents import Intent, match_rules
from app.llm.service import LLMResult
from app.mcp_server import server, tokens
from app.mcp_server.http import BearerAuth
from app.models import Role, User


@pytest.fixture
def audit(monkeypatch):
    rows = []

    async def fake_audit(identity, name, arguments, status, error, ms):
        rows.append({"name": name, "status": status, "error": error, "user": identity.user.id if identity else None})

    monkeypatch.setattr(server, "_audit", fake_audit)
    return rows


def riya() -> User:
    return User(id=10, full_name="Riya Sharma", role=Role.student, is_active=True)


async def test_tools_and_their_annotations():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert set(tools) == {
        "search_course_material",
        "ask_doubt",
        "get_learning_path",
        "my_weak_topics",
        "practice_questions",
        "check_practice_answer",
        "list_students",
    }
    assert tools["search_course_material"].annotations.readOnlyHint
    assert not tools["practice_questions"].annotations.readOnlyHint
    assert tools["check_practice_answer"].annotations.idempotentHint
    templates = {t.uriTemplate for t in await server.mcp.list_resource_templates()}
    assert templates == {"course://{code}/syllabus", "doc://{document_id}/chunks"}
    assert {p.name for p in await server.mcp.list_prompts()} == {"explain_like_beginner", "quiz_me"}


async def test_no_tool_takes_a_user_id():
    """Confused deputy: a tool acts for the token's user. A user id argument would let a client ask
    it to act for someone else."""
    for t in await server.mcp.list_tools():
        params = set(t.inputSchema.get("properties", {}))
        assert not params & {"user_id", "student_id", "user", "student", "email"}, t.name


async def test_a_call_without_identity_is_refused_and_audited(audit):
    with pytest.raises(ToolError, match="Not authenticated"):
        async with server.guarded("my_weak_topics", {}):
            pass
    assert audit == [{"name": "my_weak_topics", "status": "error", "error": audit[0]["error"], "user": None}]


async def test_rate_limit_is_checked_before_any_work(audit, monkeypatch):
    monkeypatch.setattr(server.limiter, "allow", lambda key, limit: False)
    token = server.local_identity.set(tokens.Identity(user=riya(), via="agent"))
    try:
        with pytest.raises(ToolError, match="Rate limit"):
            async with server.guarded("ask_doubt", {"question": "x"}):
                raise AssertionError("must not run")
    finally:
        server.local_identity.reset(token)
    assert audit[0]["status"] == "rate_limited" and audit[0]["user"] == 10


def test_rate_limiter_window():
    limiter = server.RateLimiter()
    assert all(limiter.allow("t", 3, now=100 + i) for i in range(3))
    assert not limiter.allow("t", 3, now=110)
    assert limiter.allow("other", 3, now=110)  # per key
    assert limiter.allow("t", 3, now=161)  # the first call left the 60 s window


def test_tokens():
    t = tokens.new_token()
    assert t.startswith("lms_") and len(t) > 40 and t != tokens.new_token()
    assert tokens.hash_token(t) == tokens.hash_token(t) and t not in tokens.hash_token(t)


async def test_http_without_a_token_gets_401(audit):
    async def app(scope, receive, send):
        raise AssertionError("the MCP layer must not see the request")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=BearerAuth(app)), base_url="http://t") as c:
        r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
        r = await c.post("/mcp", json={}, headers={"Authorization": "Bearer not-ours"})
        assert r.status_code == 401 and "revoked" in r.json()["message"]
    assert [a["status"] for a in audit] == ["refused", "refused"]


@pytest.mark.parametrize(
    "text",
    ["What should I study today?", "Make me a study plan for this week", "plan my revision please"],
)
def test_assistant_rules(text):
    assert match_rules(text).intent == Intent.assistant


def test_learning_path_rule_still_wins_for_before():
    assert match_rules("What should I learn before neural networks?").intent == Intent.learning_path


def test_tool_results_become_cards():
    step = assistant.ToolStep(
        "my_weak_topics",
        {},
        True,
        "",
        {"weak_topics": [{"topic": "Joins", "course_code": "DB201", "why": "quiz 40%", "quiz_avg": 40}]},
    )
    assert tool_card(step) == {
        "kind": "progress",
        "weak": [{"name": "Joins", "course_code": "DB201", "why": "quiz 40%"}],
    }
    step = assistant.ToolStep(
        "practice_questions",
        {},
        True,
        "",
        {
            "practice_id": 3,
            "topic": "Joins",
            "course_code": "DB201",
            "questions": [{"index": 0, "question": "Q", "options": ["a", "b", "c", "d"]}],
        },
    )
    assert tool_card(step)["practice"]["id"] == 3
    assert tool_card(assistant.ToolStep("get_learning_path", {}, True, "", {"found": False})) is None
    assert tool_card(assistant.ToolStep("my_weak_topics", {}, False, "error", None)) is None


@tool
def my_weak_topics() -> str:
    """Weak topics."""
    return "Joins: quiz average 40%"


def fake_model(script):
    calls = []

    async def chat_with_tools(session, *, messages, tools, feature, user, max_tokens=None, tool_choice=None):
        calls.append(
            {"tool_choice": tool_choice, "tool_results": [m.content for m in messages if isinstance(m, ToolMessage)]}
        )
        ai = script(len(calls), tool_choice)
        return ai, LLMResult(ai.content if isinstance(ai.content, str) else "", "fake", 100, 10, 0.0001, 5, 1)

    return chat_with_tools, calls


@pytest.fixture
def fake_tools(monkeypatch):
    @asynccontextmanager
    async def mcp_tools(user):
        yield [my_weak_topics], None

    monkeypatch.setattr(assistant, "mcp_tools", mcp_tools)


async def test_assistant_loop_calls_tools_then_answers(fake_tools, monkeypatch):
    def script(n, choice):
        if n == 1:
            return AIMessage(
                "",
                tool_calls=[
                    {"name": "my_weak_topics", "args": {}, "id": "1"},
                    {"name": "drop_tables", "args": {}, "id": "2"},
                ],
            )
        return AIMessage("Study Joins first.")

    chat, calls = fake_model(script)
    monkeypatch.setattr(assistant, "chat_with_tools", chat)
    seen = []
    run = await assistant.run(None, riya(), "What should I study?", on_step=seen.append)
    assert run.answer == "Study Joins first." and run.llm_calls == 2
    assert [(s.name, s.ok) for s in seen] == [("my_weak_topics", True), ("drop_tables", False)]
    assert calls[1]["tool_results"] == ["Joins: quiz average 40%", "Unknown tool drop_tables."]
    assert run.cost_usd == pytest.approx(0.0002)


async def test_assistant_stops_after_max_steps(fake_tools, monkeypatch):
    monkeypatch.setattr(assistant.get_settings(), "mcp_agent_max_steps", 2)

    def script(n, choice):  # a model that would call tools forever
        if choice == "none":
            return AIMessage("Here is what I found.")
        return AIMessage("", tool_calls=[{"name": "my_weak_topics", "args": {}, "id": str(n)}])

    chat, calls = fake_model(script)
    monkeypatch.setattr(assistant, "chat_with_tools", chat)
    run = await assistant.run(None, riya(), "Loop please")
    assert [c["tool_choice"] for c in calls] == [None, None, "none"]
    assert run.answer == "Here is what I found." and len(run.steps) == 2
