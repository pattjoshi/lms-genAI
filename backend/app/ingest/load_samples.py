"""Upload + index all sample course files in one go (instead of 24 manual uploads).

    uv run python -m app.ingest.load_samples

Each file in data/course_files is named like DL301_M2_Training_Neural_Networks.docx,
which tells us the course and module. It is "uploaded" as that course's teacher and runs
through exactly the same pipeline as a file uploaded from the teacher portal.
Safe to run again: unchanged files are skipped, files that failed last time are retried,
and a sample file whose content changed is indexed as a new version (v2) that replaces the old one.
"""

import asyncio
import re
import sys

from sqlalchemy import select

from app.config import REPO_ROOT
from app.db import SessionLocal, engine
from app.ingest.pipeline import process_document
from app.ingest.storage import UploadAction, UploadRefused, store_upload
from app.llm.tracing import init_tracing, shutdown_tracing
from app.models import Course, Document, Module
from app.rag import vectorstore
from app.schema import ensure_schema

SAMPLES_DIR = REPO_ROOT / "data" / "course_files"
NAME = re.compile(r"^(?P<code>[A-Z]+\d+)_M(?P<module>\d+)_")


async def main() -> int:
    from app.config import get_settings

    init_tracing(get_settings())
    async with engine.begin() as conn:
        await ensure_schema(conn)  # works even if the backend hasn't been restarted since an update
    if await vectorstore.ensure_collection() == "outdated":
        print(f"The search index is in the Phase 1 format. {vectorstore.REINDEX_HINT}", file=sys.stderr)
        await vectorstore.close()
        await engine.dispose()
        return 1
    files = sorted(p for p in SAMPLES_DIR.iterdir() if p.is_file())
    print(f"Found {len(files)} sample files in {SAMPLES_DIR}")
    total_chunks = total_tokens = 0
    total_cost = 0.0
    failed = 0

    for path in files:
        match = NAME.match(path.name)
        if not match:
            print(f"  skip  {path.name} (name doesn't match CODE_M<n>_...)")
            continue
        async with SessionLocal() as session:
            course = await session.scalar(select(Course).where(Course.code == match["code"]))
            if course is None:
                print(f"  skip  {path.name} (course {match['code']} not found — did you seed?)")
                continue
            module = await session.scalar(
                select(Module).where(Module.course_id == course.id, Module.position == int(match["module"]))
            )
            try:
                doc, action = await store_upload(
                    session,
                    data=path.read_bytes(),
                    file_name=path.name,
                    course_id=course.id,
                    module_id=module.id,
                    uploaded_by=course.teacher_id,
                    replace=True,  # the sample files are the source of truth: an edited file becomes v2
                )
            except UploadRefused as exc:
                reason = "unchanged, already indexed" if exc.code == "duplicate_file" else exc.message
                print(f"  skip  {path.name} ({reason})")
                continue
            if action == UploadAction.RETRY_FAILED:
                print(f"  retry {path.name} (failed last time)")
            elif action == UploadAction.NEW_VERSION:
                print(f"  new   {path.name} (content changed, indexing v{doc.version})")
            doc_id = doc.id

        await process_document(doc_id)

        async with SessionLocal() as session:
            doc = await session.get(Document, doc_id)
            if doc.status.value == "ready":
                total_chunks += doc.num_chunks
                total_tokens += doc.embed_tokens
                total_cost += doc.embed_cost_usd
                print(f"  ok    {path.name:45} {doc.num_chunks:3} chunks  {doc.embed_tokens:6} tokens")
            else:
                failed += 1
                print(f"  FAIL  {path.name:45} {doc.error}")
                if doc.error and ("API key" in doc.error or "budget" in doc.error or "credit" in doc.error):
                    print("Stopping: this error will repeat for every file.")
                    break

    print(f"\nIndexed {total_chunks} chunks, {total_tokens} embedding tokens, ${total_cost:.6f}. Failed: {failed}")
    shutdown_tracing()
    await vectorstore.close()
    await engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
