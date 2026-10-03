"""POST /chat/ask — answer a doubt from the course material, streamed (Server-Sent Events).

Event sequence sent to the browser:
    sources  -> the retrieved chunks (shown as citation cards)
    token    -> one piece of the answer text (many of these)
    done     -> tokens, cost, latency, status
    error    -> something failed (sent instead of / after some tokens)

Every doubt is saved in the `doubts` table (question, answer, sources, top score, cost),
which Phase 5 uses for "most asked doubts" and "content gaps".
"""

import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import CurrentUser, SessionDep
from app.config import get_settings
from app.db import SessionLocal
from app.llm.errors import LLMError
from app.llm.service import StreamStats, chat_stream
from app.llm.tracing import observe, trace
from app.models import Doubt, User
from app.prompts.rag_answer import NO_ANSWER, RAG_SYSTEM, RAG_USER, format_excerpt
from app.rag.retriever import retrieve

router = APIRouter(prefix="/chat", tags=["chat"])


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask")
async def ask(body: AskIn, user: CurrentUser):
    question = body.question.strip()
    # The request's DB session closes when this function returns, but the stream keeps
    # running, so the generator opens its own session.
    return StreamingResponse(
        _answer_stream(user.id, question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _answer_stream(user_id: int, question: str):
    s = get_settings()
    started = time.perf_counter()
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        doubt = Doubt(student_id=user.id, question=question, status="error")
        answer, stats = "", StreamStats()
        retrieval = None
        try:
            with trace("rag_answer", user, "doubt", input={"question": question}) as root:
                # 1. Retrieve
                with observe("retrieve", as_type="retriever", input={"question": question}) as span:
                    retrieval = await retrieve(session, user, question)
                    span.update(
                        output=[
                            {"score": x["score"], "file": x["file_name"], "page": x["page"], "topic": x["topic"]}
                            for x in retrieval.sources
                        ]
                    )
                doubt.sources = [{k: v for k, v in x.items() if k != "text"} for x in retrieval.sources]
                doubt.top_score = retrieval.top_score
                yield sse("sources", {"sources": retrieval.sources, "min_score": s.rag_min_score})

                used = [x for x in retrieval.sources if x["used"]]
                if not used:
                    # 2a. Nothing relevant: don't call the LLM at all (saves cost, prevents guessing).
                    answer, doubt.status = NO_ANSWER, "no_context"
                    yield sse("token", {"text": answer})
                else:
                    # 2b. Generate a grounded answer, streamed token by token
                    excerpts = "\n\n".join(format_excerpt(i, x) for i, x in enumerate(used, start=1))
                    messages = [
                        SystemMessage(RAG_SYSTEM.format(role=user.role.value, name=user.full_name)),
                        HumanMessage(RAG_USER.format(excerpts=excerpts, question=question)),
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

            total_cost = stats.cost_usd + retrieval.embed_cost_usd
            doubt.answer, doubt.cost_usd = answer, total_cost
            doubt.input_tokens, doubt.output_tokens = stats.input_tokens, stats.output_tokens
            doubt.latency_ms = int((time.perf_counter() - started) * 1000)
            yield sse(
                "done",
                {
                    "status": doubt.status,
                    "model": stats.model or None,
                    "input_tokens": stats.input_tokens,
                    "output_tokens": stats.output_tokens,
                    "embed_tokens": retrieval.embed_tokens,
                    "cost_usd": total_cost,
                    "latency_ms": doubt.latency_ms,
                    "first_token_ms": stats.first_token_ms,
                    "attempts": stats.attempts,
                    "top_score": retrieval.top_score,
                },
            )
        except LLMError as err:
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
            select(Doubt).where(Doubt.student_id == user.id).order_by(Doubt.id.desc()).limit(min(limit, 50))
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
            "cost_usd": d.cost_usd,
            "latency_ms": d.latency_ms,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in doubts
    ]
