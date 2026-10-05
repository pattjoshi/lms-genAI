"""POST /chat/ask — answer a doubt from the course material, streamed (Server-Sent Events).

Event sequence sent to the browser:
    sources  -> the retrieved chunks (citation cards) + how they were found (details panel)
    token    -> one piece of the answer text (many of these)
    done     -> tokens, cost, latency, status
    error    -> something failed (sent instead of / after some tokens)

Every doubt is saved in the `doubts` table (question, answer, sources, top score, cost),
which Phase 5 uses for "most asked doubts" and "content gaps".

Phase 2: a doubt belongs to a conversation (`conversation_id`, made by the browser and
renewed by "New chat"). The last RAG_HISTORY_TURNS doubts of the same conversation are
loaded HERE, from the database, not sent by the browser, so a client can't inject a
fake history.
"""

import json
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.auth import CurrentUser, SessionDep
from app.config import get_settings
from app.db import SessionLocal
from app.llm.errors import LLMError
from app.llm.service import StreamStats, chat_stream
from app.llm.tracing import trace
from app.models import Course, Doubt, Module, User
from app.prompts.rag_answer import NO_ANSWER, RAG_SYSTEM, RAG_USER, RAG_USER_REWRITTEN, format_excerpt
from app.rag.retriever import retrieve
from app.rag.vectorstore import IndexOutdated
from app.scopes import readable_course_ids

router = APIRouter(prefix="/chat", tags=["chat"])


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    conversation_id: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    # Optional "search only in..." filters. They can only narrow what the user may read.
    course_id: int | None = None
    module_id: int | None = None


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask")
async def ask(body: AskIn, user: CurrentUser):
    question = body.question.strip()
    # The request's DB session closes when this function returns, but the stream keeps
    # running, so the generator opens its own session.
    return StreamingResponse(
        _answer_stream(user.id, question, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _history(session, user: User, conversation_id: str | None) -> list[tuple[str, str]]:
    """Previous turns of this conversation, oldest first: [(question, answer), ...]."""
    if not conversation_id:
        return []
    rows = (
        await session.scalars(
            select(Doubt)
            .where(
                Doubt.student_id == user.id,
                Doubt.conversation_id == conversation_id,
                Doubt.hidden_at.is_(None),
                Doubt.status.in_(["answered", "no_context"]),
            )
            .order_by(Doubt.id.desc())
            .limit(get_settings().rag_history_turns)
        )
    ).all()
    return [(d.question, d.answer or "") for d in reversed(rows)]


async def _answer_stream(user_id: int, question: str, body: AskIn):
    s = get_settings()
    started = time.perf_counter()
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        doubt = Doubt(student_id=user.id, question=question, status="error", conversation_id=body.conversation_id)
        answer, stats = "", StreamStats()
        retrieval = None
        try:
            with trace(
                "rag_answer", user, "doubt", input={"question": question}, session_id=body.conversation_id
            ) as root:
                # 1. Retrieve (rewrite -> hybrid search -> rerank -> corrective retry, see retriever.py)
                history = await _history(session, user, body.conversation_id)
                retrieval = await retrieve(
                    session,
                    user,
                    question,
                    course_ids=[body.course_id] if body.course_id else None,
                    module_id=body.module_id,
                    history=history,
                )
                doubt.sources = [{k: v for k, v in x.items() if k != "text"} for x in retrieval.sources]
                doubt.top_score = retrieval.top_score
                doubt.top_rerank_score = retrieval.top_rerank_score
                searched = retrieval.retried_with or retrieval.query
                doubt.search_query = searched if searched != question else None
                yield sse(
                    "sources",
                    {
                        "sources": retrieval.sources,
                        "min_score": s.rag_min_score,
                        "min_rerank_score": s.rag_min_rerank_score,
                        "retrieval": retrieval.details(),
                    },
                )

                used = [x for x in retrieval.sources if x["used"]]
                if not used:
                    # 2a. Nothing relevant: don't call the LLM at all (saves cost, prevents guessing).
                    answer, doubt.status = NO_ANSWER, "no_context"
                    yield sse("token", {"text": answer})
                else:
                    # 2b. Generate a grounded answer, streamed token by token
                    excerpts = "\n\n".join(format_excerpt(i, x) for i, x in enumerate(used, start=1))
                    if retrieval.rewritten:
                        prompt = RAG_USER_REWRITTEN.format(
                            excerpts=excerpts, question=retrieval.query, original=question
                        )
                    else:
                        prompt = RAG_USER.format(excerpts=excerpts, question=question)
                    messages = [
                        SystemMessage(RAG_SYSTEM.format(role=user.role.value, name=user.full_name)),
                        HumanMessage(prompt),
                    ]
                    async for piece in chat_stream(
                        session,
                        messages=messages,
                        feature="rag_answer",
                        user=user,
                        stats=stats,
                        max_tokens=s.rag_max_output_tokens,
                    ):
                        answer += piece
                        yield sse("token", {"text": piece})
                    doubt.status = "no_context" if answer.strip().startswith(NO_ANSWER) else "answered"
                root.update(output={"answer": answer, "status": doubt.status})

            total_cost = stats.cost_usd + retrieval.cost_usd
            doubt.answer, doubt.cost_usd = answer, total_cost
            doubt.input_tokens = stats.input_tokens + retrieval.llm_input_tokens
            doubt.output_tokens = stats.output_tokens + retrieval.llm_output_tokens
            doubt.latency_ms = int((time.perf_counter() - started) * 1000)
            yield sse(
                "done",
                {
                    "status": doubt.status,
                    "model": stats.model or None,
                    "input_tokens": doubt.input_tokens,
                    "output_tokens": doubt.output_tokens,
                    "embed_tokens": retrieval.embed_tokens,
                    "cost_usd": total_cost,
                    "retrieval_cost_usd": retrieval.cost_usd,
                    "latency_ms": doubt.latency_ms,
                    "first_token_ms": stats.first_token_ms,
                    "attempts": stats.attempts,
                    "top_score": retrieval.top_score,
                    "relevance": retrieval.relevance(),
                },
            )
        except (LLMError, IndexOutdated) as err:
            doubt.answer = answer or None
            yield sse("error", {"code": err.code, "message": err.user_message})
        except Exception as exc:  # noqa: BLE001 - the stream must always end with an event
            doubt.answer = answer or None
            yield sse("error", {"code": "internal_error", "message": f"Something went wrong: {type(exc).__name__}"})
        finally:
            doubt.latency_ms = doubt.latency_ms or int((time.perf_counter() - started) * 1000)
            try:
                session.add(doubt)
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()


@router.get("/history")
async def history(session: SessionDep, user: CurrentUser, limit: int = 20):
    doubts = (
        await session.scalars(
            select(Doubt)
            .where(Doubt.student_id == user.id, Doubt.hidden_at.is_(None))
            .order_by(Doubt.id.desc())
            .limit(min(limit, 50))
        )
    ).all()
    return [
        {
            "id": d.id,
            "question": d.question,
            "answer": d.answer,
            "status": d.status,
            "top_score": d.top_score,
            "sources": d.sources or [],
            "conversation_id": d.conversation_id,
            "search_query": d.search_query,
            "cost_usd": d.cost_usd,
            "latency_ms": d.latency_ms,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in doubts
    ]


# Students can remove doubts from their history. This is a soft delete: the row is
# hidden from the student but kept, because Phase 5 counts questions (anonymously) to
# find "most asked doubts" and "content gaps" for teachers.


@router.delete("/history/{doubt_id}", status_code=204)
async def hide_doubt(doubt_id: int, session: SessionDep, user: CurrentUser):
    doubt = await session.get(Doubt, doubt_id)
    if doubt is None or doubt.student_id != user.id or doubt.hidden_at is not None:
        raise HTTPException(404, "Doubt not found.")  # same answer for "not yours": don't leak that it exists
    doubt.hidden_at = datetime.now(UTC)
    await session.commit()


@router.delete("/history", status_code=204)
async def hide_all_doubts(session: SessionDep, user: CurrentUser):
    await session.execute(
        update(Doubt).where(Doubt.student_id == user.id, Doubt.hidden_at.is_(None)).values(hidden_at=datetime.now(UTC))
    )
    await session.commit()


@router.get("/scope")
async def scope(session: SessionDep, user: CurrentUser):
    """Courses (with modules) this user may search: fills the "Search in" selector."""
    course_ids = await readable_course_ids(session, user)
    if not course_ids:
        return []
    courses = (await session.scalars(select(Course).where(Course.id.in_(course_ids)).order_by(Course.code))).all()
    modules = (
        await session.scalars(select(Module).where(Module.course_id.in_(course_ids)).order_by(Module.position))
    ).all()
    return [
        {
            "id": c.id,
            "code": c.code,
            "title": c.title,
            "modules": [{"id": m.id, "position": m.position, "title": m.title} for m in modules if m.course_id == c.id],
        }
        for c in courses
    ]
