"""Extract concepts for files that were indexed before Phase 3 (or whose extraction failed).

    uv run python -m app.graph.backfill            # files without concepts yet, or failed
    uv run python -m app.graph.backfill --force    # every current file again (e.g. after a prompt change)
    uv run python -m app.graph.backfill --course DL301

Files are processed one by one, in upload order, so later files can reuse the concept
names of earlier ones. Cost: about $0.05 for the 24 sample files with gpt-4o-mini.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.graph import store
from app.graph.extract import extract_document
from app.llm.tracing import init_tracing, shutdown_tracing
from app.models import Course, Document, DocumentStatus
from app.schema import ensure_schema


async def main(force: bool, course_code: str | None) -> int:
    init_tracing(get_settings())
    async with engine.begin() as conn:
        await ensure_schema(conn)
    await store.ensure_constraints()

    async with SessionLocal() as session:
        query = (
            select(Document.id, Document.file_name)
            .join(Course, Course.id == Document.course_id)
            .where(Document.superseded_at.is_(None), Document.status == DocumentStatus.ready)
            .order_by(Document.id)
        )
        if course_code:
            query = query.where(Course.code == course_code.upper())
        if not force:
            query = query.where(Document.concepts_status != "done")
        targets = (await session.execute(query)).all()
    print(f"Files to extract: {len(targets)}\n")

    failed, total_cost = 0, 0.0
    async with SessionLocal() as session:
        for doc_id, name in targets:
            await extract_document(doc_id)
            doc = await session.get(Document, doc_id)
            await session.refresh(doc)
            if doc.concepts_status == "done":
                total_cost += doc.concepts_cost_usd
                print(f"  ok    {name:45} {doc.num_concepts:3} concepts  ${doc.concepts_cost_usd:.5f}")
            else:
                failed += 1
                print(f"  FAIL  {name:45} {doc.concepts_error}")
                stop_words = ("API key", "budget", "credit", "Neo4j")
                if doc.concepts_error and any(w in doc.concepts_error for w in stop_words):
                    print("Stopping: this error will repeat for every file. Fix it and run this again.")
                    break

    print(f"\nDone. ${total_cost:.5f}, {failed} failed.")
    shutdown_tracing()
    await store.close()
    await engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-extract files that already have concepts")
    parser.add_argument("--course", help="only this course code, e.g. DL301")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.force, args.course)))
