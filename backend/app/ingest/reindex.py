"""Rebuild the search index from the uploaded files.

    uv run python -m app.ingest.reindex            # only if needed (Phase 1 index, or empty)
    uv run python -m app.ingest.reindex --force    # always (e.g. after changing CHUNK_SIZE)

Needed once after upgrading to Phase 2: a Phase 1 collection stores one vector per chunk,
Phase 2 stores two (meaning + BM25 keywords). Every current document (not old versions)
runs through the normal pipeline again. Cost: the embeddings again, about $0.001 for the
24 sample files.

How it is done here: drop the collection, create the new layout, re-process each file.
Search is empty for the minute this takes, which is fine on a dev machine. In production
you would build a NEW collection next to the old one and switch a Qdrant collection ALIAS
when it is ready (zero downtime, instant rollback). Same idea as our document versions:
index first, then swap.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.ingest.pipeline import process_document
from app.llm.tracing import init_tracing, shutdown_tracing
from app.models import Document, DocumentStatus
from app.rag import vectorstore
from app.schema import ensure_schema


async def main(force: bool) -> int:
    s = get_settings()
    init_tracing(s)
    async with engine.begin() as conn:
        await ensure_schema(conn)

    async with SessionLocal() as session:
        docs = (
            await session.scalars(
                select(Document)
                .where(
                    Document.superseded_at.is_(None), Document.status.in_([DocumentStatus.ready, DocumentStatus.failed])
                )
                .order_by(Document.id)
            )
        ).all()
        targets = [(d.id, d.file_name) for d in docs]

    state = await vectorstore.collection_state()
    points = await vectorstore.count_points() if state == "ok" else 0
    print(f"Collection '{s.qdrant_collection}': {state}, {points} points. Documents to index: {len(targets)}")
    if state == "ok" and points > 0 and not force:
        print("Already in the Phase 2 format. Nothing to do (use --force to rebuild anyway).")
        return await _close(0)

    await vectorstore.recreate_collection()
    print("Created a fresh collection (dense + bm25). Re-processing files...\n")

    failed = 0
    async with SessionLocal() as session:
        for doc_id, name in targets:
            await process_document(doc_id)
            doc = await session.get(Document, doc_id)
            await session.refresh(doc)
            if doc.status == DocumentStatus.ready:
                print(f"  ok    {name:45} {doc.num_chunks:3} chunks  {doc.embed_tokens:6} tokens")
            else:
                failed += 1
                print(f"  FAIL  {name:45} {doc.error}")
                if doc.error and any(w in doc.error for w in ("API key", "budget", "credit")):
                    print("Stopping: this error will repeat for every file. Fix it and run this again.")
                    break

    print(f"\nDone. {await vectorstore.count_points()} points indexed, {failed} failed.")
    return await _close(1 if failed else 0)


async def _close(code: int) -> int:
    shutdown_tracing()
    await vectorstore.close()
    await engine.dispose()
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="rebuild even if the index looks fine")
    sys.exit(asyncio.run(main(parser.parse_args().force)))
