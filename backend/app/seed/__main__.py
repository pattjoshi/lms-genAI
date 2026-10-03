"""Create the tables and load the dummy data into Postgres.

uv run python -m app.seed            # only if the database is empty
uv run python -m app.seed --reset    # drop everything and start fresh (also clears llm_usage)
"""

import argparse
import asyncio
import sys
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from app import models  # noqa: F401 - registers all tables on Base.metadata
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.rag import vectorstore
from app.schema import ensure_schema
from app.seed.build import build_seed

SEQUENCE_TABLES = [
    "users",
    "courses",
    "modules",
    "topics",
    "quizzes",
    "enrollments",
    "quiz_attempts",
    "payments",
    "login_events",
]


async def _reset_derived_stores() -> None:
    """--reset also clears what was built from the old data: Qdrant vectors and uploaded files."""
    try:
        await vectorstore.drop_collection()
        await vectorstore.close()
        print("Cleared Qdrant collection.")
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: could not clear Qdrant ({exc}). Is it running?", file=sys.stderr)
    upload_dir = get_settings().upload_dir
    if upload_dir.exists():
        for f in upload_dir.iterdir():
            if f.is_file():
                f.unlink()


async def main(reset: bool) -> int:
    if reset:
        await _reset_derived_stores()
    try:
        async with engine.begin() as conn:
            if reset:
                await conn.run_sync(Base.metadata.drop_all)
            await ensure_schema(conn)
    except (OperationalError, OSError) as exc:
        print(f"Cannot reach Postgres: {exc}\nIs Docker running? Try: docker compose up -d", file=sys.stderr)
        return 1

    async with SessionLocal() as session:
        if await session.scalar(select(func.count()).select_from(models.User)):
            print("Database already has data. Use --reset to wipe and re-seed.")
            return 1

        data = build_seed(now=datetime.now(UTC))
        for rows in data.tables_in_insert_order():
            session.add_all(rows)
            await session.flush()  # insert table by table so foreign keys exist
        # We inserted explicit ids, so move each id sequence past the max id.
        for table in SEQUENCE_TABLES:
            await session.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))")
            )
        await session.commit()

    roles = Counter(u.role.value for u in data.users)
    print("Seed complete:")
    print(f"  users        {len(data.users)}  {dict(roles)}")
    print(f"  courses      {len(data.courses)}  modules {len(data.modules)}  topics {len(data.topics)}")
    print(f"  enrollments  {len(data.enrollments)}")
    print(f"  quiz attempts {len(data.attempts)}")
    print(f"  payments     {len(data.payments)}")
    print(f"  login events {len(data.logins)}")
    print("Planted stories: see data/seed_stories.md")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    sys.exit(asyncio.run(main(parser.parse_args().reset)))
