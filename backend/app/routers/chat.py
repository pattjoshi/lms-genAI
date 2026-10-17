"""POST /chat/ask — every chat message, streamed (Server-Sent Events).

Phase 4: the message first goes through the agent graph (app/agent/graph.py), which routes it to a
course answer, a learning path, practice questions, progress or support.

Event sequence sent to the browser:
    route    -> which intent was chosen, by which method (rules / embedding / llm), how sure
    sources  -> doubts only: the retrieved chunks (citation cards) + how they were found (details panel)
    card     -> other intents: structured content (path steps, practice questions, weak topics...)
    token    -> one piece of the answer text (many of these)
    done     -> tokens, cost, latency, status
    error    -> something failed (sent instead of / after some tokens)

Every doubt is saved in the `doubts` table (question, answer, sources, top score, cost),
which Phase 5 uses for "most asked doubts" and "content gaps".

Phase 5: before `done`, a message that needs a person (no answer, low confidence, a login or payment
problem) opens a ticket for support (app/tickets/service.py), and `done` says which. The student can
also rate any answer (POST /chat/doubts/{id}/feedback); a 👎 opens a ticket too.

Phase 7: the graph starts with a guardrail. A refused message (prompt injection, off topic) gets a fixed
reply, a `guardrail` event, status "blocked" and no ticket; a flagged course answer gets a `guardrail` event
after its tokens. Both go into the guardrail log. Each doubt keeps its Langfuse trace id for the dashboard.

Phase 2: a doubt belongs to a conversation (`conversation_id`, made by the browser and
renewed by "New chat"). The last RAG_HISTORY_TURNS doubts of the same conversation are
loaded HERE, from the database, not sent by the browser, so a client can't inject a
fake history.
"""

import json
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.agent.graph import agent, previous_turns
from app.auth import CurrentUser, SessionDep
from app.config import get_settings
from app.db import SessionLocal
from app.llm.errors import LLMError
from app.llm.tracing import current_trace_id, trace
from app.models import Course, Doubt, Module, Ticket, User
from app.rag.vectorstore import IndexOutdated
from app.scopes import readable_course_ids
from app.tickets import service as tickets

log = logging.getLogger(__name__)
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


async def _answer_stream(user_id: int, question: str, body: AskIn):
    """Runs the agent graph (app/agent/graph.py) and turns what its nodes emit into SSE events."""
    s = get_settings()
    started = time.perf_counter()
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        doubt = Doubt(student_id=user.id, question=question, status="error", conversation_id=body.conversation_id)
        state: dict = {}
        try:
            with trace("chat", user, "doubt", input={"question": question}, session_id=body.conversation_id) as root:
                doubt.trace_id = current_trace_id()
                inputs = {
                    "session": session,
                    "user": user,
                    "question": question,
                    "conversation_id": body.conversation_id,
                    "course_id": body.course_id,
                    "module_id": body.module_id,
                    "history": await previous_turns(session, user, body.conversation_id, s.rag_history_turns),
                    "doubt": doubt,
                }
                async for mode, chunk in agent.astream(inputs, stream_mode=["custom", "values"]):
                    if mode == "custom":
                        event, data = chunk
                        yield sse(event, data)
                    else:
                        state = chunk  # the latest full state; the last one is the final state
                root.update(output={"intent": doubt.intent, "answer": doubt.answer, "status": doubt.status})

            usage = state.get("usage") or {}
            doubt.cost_usd = usage.get("cost_usd", 0.0)
            doubt.input_tokens = usage.get("input_tokens", 0)
            doubt.output_tokens = usage.get("output_tokens", 0)
            doubt.latency_ms = int((time.perf_counter() - started) * 1000)
            doubt.confidence = usage.get("confidence")
            ticket = await _auto_ticket(session, doubt, body.course_id)
            for event in state.get("guard_events") or []:
                event.doubt_id = doubt.id
                session.add(event)
            yield sse(
                "done",
                {
                    "status": doubt.status,
                    "intent": doubt.intent,
                    "model": usage.get("model"),
                    "input_tokens": doubt.input_tokens,
                    "output_tokens": doubt.output_tokens,
                    "embed_tokens": usage.get("embed_tokens", 0),
                    "cost_usd": doubt.cost_usd,
                    "retrieval_cost_usd": usage.get("retrieval_cost_usd", 0.0),
                    "latency_ms": doubt.latency_ms,
                    "first_token_ms": usage.get("first_token_ms", 0),
                    "attempts": usage.get("attempts", 0),
                    "top_score": usage.get("top_score"),
                    "relevance": usage.get("relevance"),
                    "confidence": usage.get("confidence"),
                    "checks": doubt.checks,
                    "doubt_id": doubt.id,
                    "ticket": ticket,
                },
            )
        except (LLMError, IndexOutdated) as err:
            yield sse("error", {"code": err.code, "message": err.user_message})
        except Exception as exc:  # noqa: BLE001 - the stream must always end with an event
            log.exception("Chat failed")
            yield sse("error", {"code": "internal_error", "message": f"Something went wrong: {type(exc).__name__}"})
        finally:
            doubt.latency_ms = doubt.latency_ms or int((time.perf_counter() - started) * 1000)
            try:
                session.add(doubt)
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()


async def _auto_ticket(session, doubt: Doubt, course_id: int | None) -> dict | None:
    """Save the doubt (to get its id) and open a ticket if it needs a person. A failure here must not
    lose the answer the student already has, so it is logged and skipped."""
    session.add(doubt)
    await session.flush()
    reason = tickets.auto_reason(doubt)
    if reason is None:
        return None
    try:
        async with session.begin_nested():
            ticket, _ = await tickets.open_for_doubt(session, doubt, reason, course_id)
        return {"id": ticket.id, "reason": ticket.reason, "category": ticket.category}
    except Exception:  # noqa: BLE001
        log.exception("Could not open a ticket for doubt %s", doubt.id)
        return None


class FeedbackIn(BaseModel):
    value: int = Field(ge=-1, le=1)  # 1 = 👍, -1 = 👎, 0 = take it back
    comment: str | None = Field(None, max_length=1000)


@router.post("/doubts/{doubt_id}/feedback")
async def feedback(doubt_id: int, body: FeedbackIn, session: SessionDep, user: CurrentUser):
    """S6: 👍/👎 on an answer. A 👎 opens a ticket (or marks the existing one), so a person checks it."""
    doubt = await session.get(Doubt, doubt_id)
    if doubt is None or doubt.student_id != user.id or doubt.hidden_at is not None:
        raise HTTPException(404, "Doubt not found.")
    doubt.feedback = body.value or None
    doubt.feedback_comment = (body.comment or "").strip() or None
    ticket = None
    if body.value == -1:
        t, _ = await tickets.open_for_doubt(session, doubt, "thumbs_down")
        ticket = {"id": t.id, "reason": t.reason, "category": t.category, "status": t.status}
    await session.commit()
    return {"feedback": doubt.feedback, "ticket": ticket}


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
    ticket_of = dict(
        (
            await session.execute(select(Ticket.doubt_id, Ticket.id).where(Ticket.doubt_id.in_([d.id for d in doubts])))
        ).all()
    )
    return [
        {
            "id": d.id,
            "ticket_id": ticket_of.get(d.id),
            "question": d.question,
            "answer": d.answer,
            "status": d.status,
            "intent": d.intent,
            "confidence": d.confidence,
            "feedback": d.feedback,
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
