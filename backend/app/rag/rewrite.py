"""LLM query rewriting (prompts and reasoning in app/prompts/rewrite.py).

Both calls go through the same LLM gateway as answers (budget guard, retries, circuit
breaker, cost log, Langfuse). They are optional helpers: if one fails, the caller keeps
the original question instead of failing the whole answer.
"""

from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.service import chat
from app.models import User
from app.prompts.rewrite import FOLLOWUP_SYSTEM, FOLLOWUP_USER, SEARCH_SYSTEM, SEARCH_USER, format_history

MAX_TOKENS = 80


@dataclass
class Rewrite:
    text: str
    changed: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def clean(output: str, fallback: str) -> str:
    """Models sometimes add quotes, a label or a second line. Keep the first real line."""
    for line in output.strip().splitlines():
        line = line.strip().strip('"').strip("'").strip()
        for label in ("Standalone question:", "Search query:", "Question:"):
            if line.lower().startswith(label.lower()):
                line = line[len(label) :].strip()
        if line:
            return line[:300]
    return fallback


def same_text(a: str, b: str) -> bool:
    return " ".join(a.lower().split()).rstrip("?.! ") == " ".join(b.lower().split()).rstrip("?.! ")


async def _run(session: AsyncSession, user: User, system: str, prompt: str, fallback: str, feature: str) -> Rewrite:
    result = await chat(
        session,
        messages=[SystemMessage(system), HumanMessage(prompt)],
        feature=feature,
        user=user,
        max_tokens=MAX_TOKENS,
    )
    text = clean(result.text, fallback)
    return Rewrite(
        text=text,
        changed=not same_text(text, fallback),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
    )


async def standalone_question(
    session: AsyncSession, user: User, question: str, history: list[tuple[str, str]]
) -> Rewrite:
    """Follow-up -> standalone question, using the previous turns of the same chat."""
    prompt = FOLLOWUP_USER.format(history=format_history(history), question=question)
    return await _run(session, user, FOLLOWUP_SYSTEM, prompt, question, "rag_rewrite")


async def search_query(session: AsyncSession, user: User, question: str) -> Rewrite:
    """Question -> textbook-style search query (corrective retry)."""
    return await _run(session, user, SEARCH_SYSTEM, SEARCH_USER.format(question=question), question, "rag_corrective")
