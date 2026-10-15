"""The knowledge base (P5): answers support wrote, searched next to the course material.

When support resolves a course question and keeps "save to knowledge base" ticked, the question, its vector
and the answer become a FaqEntry. Retrieval (app/rag/retriever.py, last step) compares the student's
question with these entries; one that means the same thing (cosine >= FAQ_MIN_SIMILARITY) is put in front of
the course passages as a verified source, so the AI answers from it and cites it like any other excerpt.

Why a high threshold: a support answer was written for ONE question. "What is dropout?" and "Why does dropout
work?" are close in meaning but need different answers, so only near-paraphrases should reuse it.

Scope: an entry belongs to a course, and it is only searched for people who may read that course, exactly
like the course material itself.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Course, FaqEntry
from app.tickets import vectors

LABEL = "Support answer (verified)"


async def search(session: AsyncSession, query_vec: list[float], course_ids: list[int], k: int = 2) -> list[dict]:
    """Knowledge-base entries matching the question, as retrieval sources (best first)."""
    if not query_vec or not course_ids:
        return []
    rows = (
        await session.execute(
            select(FaqEntry, Course.code)
            .join(Course, Course.id == FaqEntry.course_id)
            .where(FaqEntry.active.is_(True), FaqEntry.course_id.in_(course_ids))
        )
    ).all()
    found = vectors.nearest(
        query_vec, [((f, code), f.question_vec) for f, code in rows], get_settings().faq_min_similarity, k
    )
    return [as_source(f, code, sim) for (f, code), sim in found]


def as_source(f: FaqEntry, course_code: str, similarity: float) -> dict:
    return {
        "rank": 0,
        "score": round(similarity, 4),
        "dense_rank": None,
        "keyword_rank": None,
        "rrf": None,
        "rerank_score": None,
        "used": True,
        "text": f"Question: {f.question}\nAnswer: {f.answer}",
        "file_name": LABEL,
        "file_type": "faq",
        "page": None,
        "section": None,
        "topic": None,
        "course_code": course_code,
        "module_id": None,
        "document_id": None,
        "chunk_index": None,
        "faq_id": f.id,
    }
