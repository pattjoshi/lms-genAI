"""Run one checked query as the read-only user, scoped to the person asking (Phase 6).

    reader connection ──► its backend pid
    owner connection  ──► sql_agent_scope: (pid, user, role)        the RLS policies read this
    reader connection ──► BEGIN READ ONLY; SET LOCAL statement_timeout; SELECT ... LIMIT max+1; ROLLBACK
    owner connection  ──► delete the scope row

Limits: rows (SQL_AGENT_MAX_ROWS, one extra row is fetched to know there were more), time
(SQL_AGENT_TIMEOUT_MS, enforced by Postgres), and the transaction is rolled back even though nothing
could be written.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.db import engine as owner_engine
from app.models import User
from app.sql_agent.access import SCOPE_TABLE

_reader_engine: AsyncEngine | None = None


def reader_engine() -> AsyncEngine:
    global _reader_engine
    if _reader_engine is None:
        _reader_engine = create_async_engine(
            get_settings().sql_agent_database_url, pool_size=2, max_overflow=3, pool_pre_ping=True
        )
    return _reader_engine


async def close() -> None:
    global _reader_engine
    if _reader_engine is not None:
        await _reader_engine.dispose()
        _reader_engine = None


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]  # raw Python values (numbers stay numbers for the chart rules)
    truncated: bool = False
    ms: int = 0
    extra: dict = field(default_factory=dict)


class QueryFailed(Exception):
    """retryable: a SQL error the model can fix (bad column, type error). Not retryable: setup problems."""

    def __init__(self, message: str, *, retryable: bool = True, stage: str = "run"):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.stage = stage


def _db_message(exc: DBAPIError) -> str:
    msg = str(exc.orig) if exc.orig is not None else str(exc)
    msg = re.sub(r"^<class '[\w.]+'>:\s*", "", msg)  # asyncpg errors come wrapped as "<class '...'>: text"
    return msg.splitlines()[0][:300] if msg else type(exc).__name__


async def run_scoped(
    user: User,
    sql: str,
    *,
    max_rows: int | None = None,
    owner: AsyncEngine | None = None,
    reader: AsyncEngine | None = None,
) -> QueryResult:
    settings = get_settings()
    max_rows = max_rows or settings.sql_agent_max_rows
    owner = owner or owner_engine
    reader = reader or reader_engine()

    try:
        conn = await reader.connect()
    except (OperationalError, DBAPIError, OSError) as exc:
        raise QueryFailed(
            "The SQL agent's read-only database user can't log in. Restart the backend (it creates the user) "
            "and check SQL_AGENT_DB_PASSWORD in .env.",
            retryable=False,
            stage="setup",
        ) from exc

    try:
        pid = await conn.scalar(text("SELECT pg_backend_pid()"))
        await conn.rollback()
        async with owner.begin() as o:
            await o.execute(
                text(
                    f"INSERT INTO {SCOPE_TABLE} (pid, user_id, role) VALUES (:pid, :uid, :role) "
                    "ON CONFLICT (pid) DO UPDATE SET user_id = EXCLUDED.user_id, role = EXCLUDED.role, "
                    "created_at = now()"
                ),
                {"pid": pid, "uid": user.id, "role": user.role.value},
            )
        try:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(text(f"SET LOCAL statement_timeout = {int(settings.sql_agent_timeout_ms)}"))
            started = datetime.now()
            # exec_driver_sql: the model's SQL goes to Postgres as written (text() would treat ':x' as a
            # parameter). The newline before ')' ends a trailing "-- comment".
            result = await conn.exec_driver_sql(f"SELECT * FROM (\n{sql}\n) AS agent_query LIMIT {max_rows + 1}")
            columns = list(result.keys())
            rows = [tuple(r) for r in result.fetchall()]
            ms = int((datetime.now() - started).total_seconds() * 1000)
        except DBAPIError as exc:
            message = _db_message(exc)
            if "statement timeout" in message:
                raise QueryFailed(
                    f"The query took longer than {settings.sql_agent_timeout_ms} ms and was stopped. "
                    "Write a simpler query (fewer joins, aggregate earlier).",
                    stage="timeout",
                ) from None
            raise QueryFailed(message) from None
        finally:
            await conn.rollback()
            async with owner.begin() as o:
                await o.execute(text(f"DELETE FROM {SCOPE_TABLE} WHERE pid = :pid"), {"pid": pid})
    finally:
        await conn.close()

    return QueryResult(columns=columns, rows=rows[:max_rows], truncated=len(rows) > max_rows, ms=ms)


def jsonable(value: Any) -> Any:
    """A database value as JSON for the browser."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    return str(value)
