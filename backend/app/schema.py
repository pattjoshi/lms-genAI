"""Keep the database schema up to date without wiping data.

`create_all` creates missing TABLES but never changes existing ones. When a later
change adds a COLUMN to an existing table, we add it here with idempotent SQL
(`IF NOT EXISTS`), so everyone's existing database is upgraded on the next start.

In a bigger project this is what a migration tool (Alembic) does, with versioned,
reversible migration files. A short list of safe ALTERs is enough for this project.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import models  # noqa: F401 - registers all tables on Base.metadata
from app.db import Base

UPGRADES = [
    # Phase 1 fixes: document versioning
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS replaces_id INTEGER REFERENCES documents(id) ON DELETE SET NULL",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ",
    # Phase 1 fixes: students can remove doubts from their history
    "ALTER TABLE doubts ADD COLUMN IF NOT EXISTS hidden_at TIMESTAMPTZ",
    # Phase 2: follow-up questions and query rewriting
    "ALTER TABLE doubts ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS ix_doubts_conversation_id ON doubts (conversation_id)",
    "ALTER TABLE doubts ADD COLUMN IF NOT EXISTS search_query TEXT",
    "ALTER TABLE doubts ADD COLUMN IF NOT EXISTS top_rerank_score DOUBLE PRECISION",
]


async def ensure_schema(conn: AsyncConnection) -> None:
    await conn.run_sync(Base.metadata.create_all)
    for statement in UPGRADES:
        await conn.execute(text(statement))
