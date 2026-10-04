"""Qdrant access: one collection, `course_chunks`, holding every chunk's vectors + payload.

Phase 2: each point stores TWO vectors (Qdrant "named vectors"):
    dense -> the OpenAI embedding (meaning)
    bm25  -> a sparse keyword vector (see sparse.py); Qdrant adds the IDF part itself

Payload = the metadata stored next to the vectors. It is what makes filtering possible
("only courses 1 and 3", "only module 7") and what the citation is built from (file
name, page, section). Payload indexes make those filters fast.

A Phase 1 collection has a single unnamed vector. It can't hold keyword vectors, so it
must be rebuilt once:  uv run python -m app.ingest.reindex
"""

import logging
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient, models

from app.config import get_settings
from app.rag.sparse import SparseVector

log = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "bm25"

# Fields we filter on. Keyword = exact match; integer = numeric match/range.
PAYLOAD_INDEXES = {
    "course_id": models.PayloadSchemaType.INTEGER,
    "module_id": models.PayloadSchemaType.INTEGER,
    "document_id": models.PayloadSchemaType.INTEGER,
    "file_type": models.PayloadSchemaType.KEYWORD,
    "topic": models.PayloadSchemaType.KEYWORD,
}

REINDEX_HINT = "Run once (from backend/): uv run python -m app.ingest.reindex"

_client: AsyncQdrantClient | None = None
_schema_ok = False  # cached after the first successful check


class IndexOutdated(Exception):
    """The collection was built by Phase 1 (one unnamed vector) and has no keyword vectors."""

    code = "reindex_needed"
    user_message = f"The search index is from an older version and must be rebuilt. {REINDEX_HINT}"


def client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=get_settings().qdrant_url, timeout=10)
    return _client


async def close() -> None:
    global _client, _schema_ok
    if _client is not None:
        await _client.close()
        _client = None
    _schema_ok = False


async def collection_state() -> str:
    """'missing', 'ok' (hybrid layout) or 'outdated' (Phase 1 layout)."""
    s = get_settings()
    if not await client().collection_exists(s.qdrant_collection):
        return "missing"
    info = await client().get_collection(s.qdrant_collection)
    vectors = info.config.params.vectors
    sparse = info.config.params.sparse_vectors or {}
    if isinstance(vectors, dict) and DENSE in vectors and SPARSE in sparse:
        return "ok"
    return "outdated"


async def _create() -> None:
    s = get_settings()
    c = client()
    await c.create_collection(
        s.qdrant_collection,
        vectors_config={DENSE: models.VectorParams(size=s.embedding_dim, distance=models.Distance.COSINE)},
        # IDF modifier: Qdrant computes "how rare is this word" over the whole collection at query time.
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    for field, schema in PAYLOAD_INDEXES.items():
        await c.create_payload_index(s.qdrant_collection, field_name=field, field_schema=schema)
    log.info("Created Qdrant collection %s (dense %d-dim cosine + bm25 sparse)", s.qdrant_collection, s.embedding_dim)


async def ensure_collection() -> str:
    """Create the collection if missing. Never deletes data: an outdated one is only reported."""
    global _schema_ok
    state = await collection_state()
    if state == "missing":
        await _create()
        state = "ok"
    if state == "outdated":
        log.warning("Qdrant collection %s is in the Phase 1 format. %s", get_settings().qdrant_collection, REINDEX_HINT)
    _schema_ok = state == "ok"
    return state


async def _require_current_schema() -> None:
    if not _schema_ok and await ensure_collection() != "ok":
        raise IndexOutdated(IndexOutdated.user_message)


async def recreate_collection() -> None:
    """Drop and create empty (used by the re-index command)."""
    global _schema_ok
    await drop_collection()
    await _create()
    _schema_ok = True


async def drop_collection() -> None:
    global _schema_ok
    s = get_settings()
    if await client().collection_exists(s.qdrant_collection):
        await client().delete_collection(s.qdrant_collection)
    _schema_ok = False


async def count_points() -> int:
    s = get_settings()
    if not await client().collection_exists(s.qdrant_collection):
        return 0
    return (await client().count(s.qdrant_collection, exact=True)).count


def point(point_id: str, dense: list[float], sparse: SparseVector, payload: dict) -> models.PointStruct:
    vector: dict = {DENSE: dense}
    if sparse:  # a chunk of only stop words has no keyword vector
        vector[SPARSE] = models.SparseVector(indices=sparse.indices, values=sparse.values)
    return models.PointStruct(id=point_id, vector=vector, payload=payload)


async def upsert(points: list[models.PointStruct]) -> None:
    await _require_current_schema()
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
    id: str
    score: float  # dense: cosine similarity (1 = same direction, ~0 = unrelated); bm25: keyword score
    payload: dict


def build_filter(course_ids: list[int], module_id: int | None = None) -> models.Filter:
    must = [models.FieldCondition(key="course_id", match=models.MatchAny(any=course_ids))]
    if module_id is not None:
        must.append(models.FieldCondition(key="module_id", match=models.MatchValue(value=module_id)))
    return models.Filter(must=must)


def _hits(response) -> list[Hit]:
    return [Hit(id=str(p.id), score=p.score, payload=p.payload or {}) for p in response.points]


async def search(
    dense: list[float],
    sparse: SparseVector | None,
    course_ids: list[int],
    limit: int,
    module_id: int | None = None,
) -> tuple[list[Hit], list[Hit]]:
    """(meaning hits, keyword hits), each best first. Keyword hits are [] when `sparse` is None/empty.

    Both searches go to Qdrant in ONE request (query_batch_points). The filter is applied
    INSIDE each search (pre-filtering), not on the results afterwards: post-filtering the
    top 20 could leave zero chunks of the student's courses.
    """
    if not course_ids:
        return [], []
    await _require_current_schema()
    flt = build_filter(course_ids, module_id)
    requests = [models.QueryRequest(query=dense, using=DENSE, filter=flt, limit=limit, with_payload=True)]
    if sparse:
        requests.append(
            models.QueryRequest(
                query=models.SparseVector(indices=sparse.indices, values=sparse.values),
                using=SPARSE,
                filter=flt,
                limit=limit,
                with_payload=True,
            )
        )
    responses = await client().query_batch_points(get_settings().qdrant_collection, requests=requests)
    return _hits(responses[0]), (_hits(responses[1]) if len(responses) > 1 else [])
