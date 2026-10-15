"""Generation half of RAG, shared by the chat (streamed) and the MCP `ask_doubt` tool (one response).

The chat's doubt node streams tokens to the browser; an MCP client wants one result with the answer
and its sources. Both build the SAME prompt here, so a fix to the prompt reaches both.
"""

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.service import chat
from app.models import User
from app.prompts.rag_answer import NO_ANSWER, RAG_MEMORY, RAG_SYSTEM, RAG_USER, RAG_USER_REWRITTEN, format_excerpt
from app.rag.retriever import Retrieval, retrieve


def confidence(relevance: dict) -> str:
    """S7: how sure the answer is, from how far the best source cleared the relevance threshold.
    A score just above the threshold means the AI got material that is only loosely related.
    Phase 5: an answer support already verified for this question counts as high."""
    if relevance.get("faq"):
        return "high"
    best, threshold = relevance.get("best"), relevance.get("threshold") or 0
    if best is None:
        return "low"
    margin = best - threshold
    span = 0.3 if relevance.get("by") == "rerank" else 0.15  # cosine scores sit in a narrower band
    return "high" if margin >= span else "medium" if margin >= span / 3 else "low"


def rag_messages(user: User, question: str, retrieval: Retrieval, weak: list[str] | None = None) -> list[BaseMessage]:
    """System rules + numbered excerpts (only the sources marked `used`) + the question."""
    used = [x for x in retrieval.sources if x["used"]]
    excerpts = "\n\n".join(format_excerpt(i, x) for i, x in enumerate(used, start=1))
    if retrieval.rewritten:
        prompt = RAG_USER_REWRITTEN.format(excerpts=excerpts, question=retrieval.query, original=question)
    else:
        prompt = RAG_USER.format(excerpts=excerpts, question=question)
    system = RAG_SYSTEM.format(role=user.role.value, name=user.full_name)
    if weak:
        system += RAG_MEMORY.format(topics=", ".join(weak))
    return [SystemMessage(system), HumanMessage(prompt)]


def cited(retrieval: Retrieval) -> list[dict]:
    """The sources the answer may cite, numbered like the excerpts in the prompt ([1], [2], ...)."""
    used = [x for x in retrieval.sources if x["used"]]
    return [
        {
            "n": i,
            "course_code": x.get("course_code"),
            "file_name": x.get("file_name"),
            "page": x.get("page"),
            "section": x.get("section"),
        }
        for i, x in enumerate(used, start=1)
    ]


async def answer(
    session: AsyncSession,
    user: User,
    question: str,
    *,
    course_ids: list[int] | None = None,
    weak: list[str] | None = None,
    feature: str = "rag_answer",
) -> dict:
    """Retrieve, then answer in one LLM call (no streaming). No relevant source = no LLM call."""
    retrieval = await retrieve(session, user, question, course_ids=course_ids)
    if not retrieval.has_context:
        return {"answer": NO_ANSWER, "sources": [], "confidence": None, "cost_usd": round(retrieval.cost_usd, 6)}
    result = await chat(
        session,
        messages=rag_messages(user, question, retrieval, weak),
        feature=feature,
        user=user,
        max_tokens=get_settings().rag_max_output_tokens,
    )
    return {
        "answer": result.text,
        "sources": cited(retrieval),
        "confidence": confidence(retrieval.relevance()),
        "cost_usd": round(result.cost_usd + retrieval.cost_usd, 6),
    }
