"""Qdrant access: one collection, `course_chunks`, holding every chunk's vector + payload.

Payload = the metadata stored next to each vector. It is what makes filtering possible
("only courses 1 and 3") and what the citation is built from (file name, page, section).
Payload indexes make those filters fast.
"""

import logging
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient, models

from app.config import get_settings

log = logging.getLogger(__name__)

# Fields we filter on. Keyword = exact match; integer = numeric match/range.
PAYLOAD_INDEXES = {
    "course_id": models.PayloadSchemaType.INTEGER,
    "module_id": models.PayloadSchemaType.INTEGER,
    "document_id": models.PayloadSchemaType.INTEGER,
    "file_type": models.PayloadSchemaType.KEYWORD,
    "topic": models.PayloadSchemaType.KEYWORD,
}

_client: AsyncQdrantClient | None = None


def client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=get_settings().qdrant_url, timeout=10)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def ensure_collection() -> None:
    """Create the collection (cosine distance) and payload indexes if they don't exist yet."""
    s = get_settings()
    c = client()
    if not await c.collection_exists(s.qdrant_collection):
        await c.create_collection(
            s.qdrant_collection,
            vectors_config=models.VectorParams(size=s.embedding_dim, distance=models.Distance.COSINE),
        )
        for field, schema in PAYLOAD_INDEXES.items():
            await c.create_payload_index(s.qdrant_collection, field_name=field, field_schema=schema)
        log.info("Created Qdrant collection %s (dim=%d, cosine)", s.qdrant_collection, s.embedding_dim)


async def drop_collection() -> None:
    s = get_settings()
    if await client().collection_exists(s.qdrant_collection):
        await client().delete_collection(s.qdrant_collection)


async def upsert(points: list[models.PointStruct]) -> None:
    await client().upsert(get_settings().qdrant_collection, points=points, wait=True)


async def delete_document(document_id: int) -> None:
    s = get_settings()
    if not await client().collection_exists(s.qdrant_collection):
        return
    await client().delete(
        s.qdrant_collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
            )
        ),
        wait=True,
    )


@dataclass
class Hit:
    score: float  # cosine similarity: 1 = same direction, ~0 = unrelated
    payload: dict


async def search(vector: list[float], course_ids: list[int], top_k: int) -> list[Hit]:
    """Nearest chunks to `vector`, restricted to `course_ids`.

    The course filter is applied INSIDE the vector search (pre-filtering), not on the
    results afterwards. Post-filtering top-5 results could leave you with zero chunks.
    """
    if not course_ids:
        return []
    s = get_settings()
    response = await client().query_points(
        s.qdrant_collection,
        query=vector,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="course_id", match=models.MatchAny(any=course_ids))]
        ),
        limit=top_k,
        with_payload=True,
    )
    return [Hit(score=p.score, payload=p.payload or {}) for p in response.points]
