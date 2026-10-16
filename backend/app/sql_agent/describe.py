"""What the model is told about the database, and what the user is told about their scope (Phase 6).

Schema-aware prompting: the model can only write good SQL for tables it understands. The description is
read from Postgres itself: table and column comments (written as `comment=` in models.py), types, and
foreign keys, for the agent's tables only, and only the columns the read-only user may select. A
column added later with a comment shows up in the prompt with no prompt change.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role
from app.permissions import Resource, Scope, scope_for
from app.sql_agent.access import AGENT_TABLES

_cache: str | None = None

_TYPES = {
    "character varying": "text",
    "timestamp with time zone": "timestamptz",
    "double precision": "float",
}


def _short_type(t: str) -> str:
    base = t.split("(")[0]
    return _TYPES.get(base, base)


async def schema_text(session: AsyncSession, *, refresh: bool = False) -> str:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    names = [t.name for t in AGENT_TABLES]
    hidden = {(t.name, c) for t in AGENT_TABLES for c in t.hidden}
    columns = (
        await session.execute(
            text(
                """SELECT c.relname, obj_description(c.oid, 'pg_class'), a.attname,
                          format_type(a.atttypid, a.atttypmod), col_description(c.oid, a.attnum)
                   FROM pg_class c
                   JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
                   JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                   WHERE c.relname = ANY(:names) AND c.relkind = 'r'
                   ORDER BY c.relname, a.attnum"""
            ),
            {"names": names},
        )
    ).all()
    fks = (
        await session.execute(
            text(
                """SELECT t.relname, a.attname, r.relname, ra.attname
                   FROM pg_constraint k
                   JOIN pg_class t ON t.oid = k.conrelid
                   JOIN pg_class r ON r.oid = k.confrelid
                   JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
                   JOIN pg_attribute ra ON ra.attrelid = k.confrelid AND ra.attnum = k.confkey[1]
                   WHERE k.contype = 'f' AND t.relname = ANY(:names)"""
            ),
            {"names": names},
        )
    ).all()
    refs = {(t, c): f"{rt}.{rc}" for t, c, rt, rc in fks if rt in names}

    by_table: dict[str, tuple[str | None, list[str]]] = {}
    for table, table_comment, column, col_type, comment in columns:
        if (table, column) in hidden:
            continue
        line = f"- {column} {_short_type(col_type)}"
        if ref := refs.get((table, column)):
            line += f" -> {ref}"
        if comment:
            line += f": {comment}"
        by_table.setdefault(table, (table_comment, []))[1].append(line)

    parts = []
    for name in names:  # keep AGENT_TABLES order: catalogue first, then people and their records
        if name in by_table:
            comment, lines = by_table[name]
            parts.append(f"### {name}" + (f": {comment}" if comment else "") + "\n" + "\n".join(lines))
    _cache = "\n\n".join(parts)
    return _cache


LABELS = {
    Resource.STUDENT_RECORDS: "Student profiles, enrollments and quiz scores",
    Resource.PAYMENTS: "Payments",
    Resource.ACCOUNT_ACTIVITY: "Login history",
    Resource.TICKETS: "Support tickets",
    Resource.AI_USAGE: "AI usage and cost",
}

SCOPE_WORDS = {
    Scope.ALL: "all",
    Scope.OWN: "only your own",
    Scope.OWN_COURSES: "only in the courses you teach",
    Scope.TICKET_STUDENT: "only students with an open ticket",
    Scope.ENROLLED: "only your enrolled courses",
    Scope.NONE: "none",
}


def scope_summary(role: Role) -> list[dict]:
    """The permission matrix rows the SQL agent uses, in words, for one role."""
    rows = [{"data": "Course catalogue (courses, modules, topics, quizzes) and staff names", "scope": "all"}]
    rows += [{"data": label, "scope": SCOPE_WORDS[scope_for(role, r)]} for r, label in LABELS.items()]
    return rows


def scope_sentence(role: Role) -> str:
    return "; ".join(f"{r['data']}: {r['scope']}" for r in scope_summary(role))
