"""Query pipeline, retrieval half: question -> embedding -> nearest chunks.

Security note: the course filter comes from the user's identity (permission matrix),
NEVER from the question or the LLM. A student can only ever retrieve chunks of courses
they are enrolled in, whatever they type.
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.service import embed_texts
from app.models import User
from app.rag import vectorstore
from app.scopes import readable_course_ids


@dataclass
class Retrieval:
    sources: list[dict] = field(default_factory=list)  # ranked, best first
    embed_tokens: int = 0
    embed_cost_usd: float = 0.0
    course_ids: list[int] = field(default_factory=list)

    @property
    def top_score(self) -> float | None:
        return self.sources[0]["score"] if self.sources else None


async def retrieve(
    session: AsyncSession, user: User, question: str, top_k: int | None = None, course_ids: list[int] | None = None
) -> Retrieval:
    s = get_settings()
    allowed = await readable_course_ids(session, user)
    # An explicit course_ids (evals) can only NARROW the allowed set, never widen it.
    course_ids = [c for c in course_ids if c in allowed] if course_ids is not None else allowed
    result = Retrieval(course_ids=course_ids)
    if not course_ids:
        return result

    embedded = await embed_texts(session, [question], feature="rag_embed_query", user=user)
    result.embed_tokens, result.embed_cost_usd = embedded.tokens, embedded.cost_usd

    hits = await vectorstore.search(embedded.vectors[0], course_ids, top_k or s.rag_top_k)
    for rank, hit in enumerate(hits, start=1):
        p = hit.payload
        result.sources.append(
            {
                "rank": rank,
                "score": round(hit.score, 4),
                "used": hit.score >= s.rag_min_score,  # only these go into the prompt
                "text": p.get("text", ""),
                "file_name": p.get("file_name"),
                "file_type": p.get("file_type"),
                "page": p.get("page"),
                "section": p.get("section"),
                "topic": p.get("topic"),
                "course_code": p.get("course_code"),
                "document_id": p.get("document_id"),
                "chunk_index": p.get("chunk_index"),
            }
        )
    return result
