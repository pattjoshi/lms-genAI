"""The indexing pipeline: uploaded file -> searchable chunks in Qdrant.

    uploaded -> parsing -> chunking -> embedding -> tagging -> indexing -> ready
                                                                       \\-> failed (+ error)

Each step updates `documents.status`, so the teacher's page can show live progress.
Any exception marks the document `failed` with a readable error; it can be re-processed.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.ingest.chunker import chunk_sections
from app.ingest.parsers import ParseError, parse_file
from app.ingest.tagger import fill_missing_headings, tag_chunk
from app.llm.errors import LLMError
from app.llm.service import embed_texts
from app.llm.tracing import observe, trace
from app.models import Chunk, Course, Document, DocumentStatus, Module, Topic, User
from app.rag import sparse, vectorstore

log = logging.getLogger(__name__)


async def _set_status(session: AsyncSession, doc: Document, status: DocumentStatus) -> None:
    doc.status = status
    await session.commit()


async def process_document(document_id: int) -> None:
    """Run the whole pipeline for one document. Safe to call again (re-processing)."""
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.superseded_at is not None:
            return  # deleted, or an old version that a newer one replaced
        uploader = await session.get(User, doc.uploaded_by)
        try:
            with trace("ingest_document", uploader, "ingest", input={"file": doc.file_name}) as root:
                await _run(session, doc, uploader)
                root.update(output={"chunks": doc.num_chunks, "tokens": doc.embed_tokens})
        except Exception as exc:  # noqa: BLE001 - every failure must end in a visible status
            await session.rollback()
            doc = await session.get(Document, document_id)
            if isinstance(exc, (ParseError, LLMError, vectorstore.IndexOutdated)):
                doc.error = getattr(exc, "user_message", None) or str(exc)
            else:
                log.exception("Ingestion failed for document %s", document_id)
                doc.error = f"Unexpected error: {type(exc).__name__}: {exc}"[:500]
            doc.status = DocumentStatus.failed
            await session.commit()


async def _run(session: AsyncSession, doc: Document, uploader: User | None) -> None:
    s = get_settings()
    doc.error = None

    # 1. Parse (CPU work -> thread, so the API stays responsive)
    await _set_status(session, doc, DocumentStatus.parsing)
    with observe("parse", input={"file_type": doc.file_type}) as span:
        sections = await asyncio.to_thread(parse_file, Path(doc.stored_path), doc.file_type)
        span.update(output={"sections": len(sections)})
    doc.num_pages = max((sec.page or 0) for sec in sections) or None

    # 2. Chunk
    await _set_status(session, doc, DocumentStatus.chunking)
    drafts = chunk_sections(sections, s.chunk_size, s.chunk_overlap)
    if not drafts:
        raise ParseError("The file has text, but nothing long enough to index.")

    # 3. Embed chunks + this module's topic names in ONE request batch (topic vectors are for tagging)
    await _set_status(session, doc, DocumentStatus.embedding)
    module = await session.get(Module, doc.module_id)
    course = await session.get(Course, doc.course_id)
    topics = (await session.scalars(select(Topic).where(Topic.module_id == module.id).order_by(Topic.position))).all()
    topic_texts = [f"{t.name} ({module.title}, {course.title})" for t in topics]
    embedded = await embed_texts(
        session, [d.text for d in drafts] + topic_texts, feature="embed_document", user=uploader
    )
    chunk_vectors, topic_vectors = embedded.vectors[: len(drafts)], embedded.vectors[len(drafts) :]

    # 4. Tag each chunk with its topic + difficulty
    await _set_status(session, doc, DocumentStatus.tagging)
    topic_list = [(t.name, t.difficulty.value) for t in topics]
    fill_missing_headings(drafts, [t.name for t in topics])  # PDFs: recover headings from reading order
    tags = [tag_chunk(d.section, v, topic_list, topic_vectors) for d, v in zip(drafts, chunk_vectors, strict=True)]

    # 5. Index: replace any previous chunks of this document (re-processing), then upsert
    await _set_status(session, doc, DocumentStatus.indexing)
    if await vectorstore.ensure_collection() != "ok":
        raise vectorstore.IndexOutdated(vectorstore.IndexOutdated.user_message)  # check BEFORE deleting anything
    await vectorstore.delete_document(doc.id)
    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))

    points, rows = [], []
    for draft, vector, tag in zip(drafts, chunk_vectors, tags, strict=True):
        point_id = str(uuid.uuid4())
        payload = {
            "document_id": doc.id,
            "chunk_index": draft.index,
            "text": draft.text,
            "file_name": doc.file_name,
            "file_type": doc.file_type,
            "course_id": course.id,
            "course_code": course.code,
            "module_id": module.id,
            "module_title": module.title,
            "page": draft.page,
            "section": draft.section,
            "topic": tag.topic if tag else None,
            "difficulty": tag.difficulty if tag else None,
        }
        # Two vectors per chunk: meaning (embedding) + keywords (BM25, computed locally, free)
        points.append(vectorstore.point(point_id, vector, sparse.encode_document(draft.text), payload))
        rows.append(
            Chunk(
                document_id=doc.id,
                chunk_index=draft.index,
                text=draft.text,
                page=draft.page,
                section=draft.section,
                topic=payload["topic"],
                difficulty=payload["difficulty"],
                topic_score=tag.score if tag else None,
                point_id=point_id,
            )
        )
    await vectorstore.upsert(points)
    session.add_all(rows)

    doc.num_chunks = len(rows)
    doc.embed_tokens = embedded.tokens
    doc.embed_cost_usd = embedded.cost_usd
    doc.processed_at = datetime.now(UTC)
    doc.status = DocumentStatus.ready
    await session.commit()
    log.info("Indexed %s: %d chunks, %d tokens, $%.6f", doc.file_name, len(rows), embedded.tokens, embedded.cost_usd)

    if doc.replaces_id:
        await _retire_previous_version(session, doc)


async def _retire_previous_version(session: AsyncSession, doc: Document) -> None:
    """The new version is live, so take the old one out of search ("index first, then swap").

    If indexing the new version had failed we would never get here, and students keep
    getting answers from the old version. A short overlap is better than a gap.
    """
    old = await session.get(Document, doc.replaces_id)
    if old is None or old.superseded_at is not None:
        return
    await vectorstore.delete_document(old.id)
    await session.execute(delete(Chunk).where(Chunk.document_id == old.id))
    old.superseded_at = datetime.now(UTC)
    old.num_chunks = 0
    await session.commit()
    log.info("%s v%d replaced v%d", doc.file_name, doc.version, old.version)
