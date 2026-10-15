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
    # Phase 3: concept extraction status per file
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS concepts_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS concepts_error TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS num_concepts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS concepts_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0",
    # Phase 3c: generated quizzes (questions live in the new quiz_questions table)
    "ALTER TABLE quizzes ALTER COLUMN topic_id DROP NOT NULL",
    "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS course_id INTEGER REFERENCES courses(id)",
    "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'published'",
    "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)",
    "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL",
    "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS source_label VARCHAR(255)",
    "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS generation_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ",
    """UPDATE quizzes q SET course_id = m.course_id FROM topics t JOIN modules m ON m.id = t.module_id
       WHERE q.course_id IS NULL AND q.topic_id = t.id""",
    "ALTER TABLE quiz_attempts ADD COLUMN IF NOT EXISTS answers JSON",
    # Phase 4a: chat routing (new tables learner_topics and practice_sets are created by create_all)
    "ALTER TABLE doubts ADD COLUMN IF NOT EXISTS intent VARCHAR(20)",
    "ALTER TABLE doubts ADD COLUMN IF NOT EXISTS route JSON",
]


async def ensure_schema(conn: AsyncConnection) -> None:
    await conn.run_sync(Base.metadata.create_all)
    for statement in UPGRADES:
        await conn.execute(text(statement))
