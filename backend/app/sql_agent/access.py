"""Layer 3 for LLM-written SQL: a read-only Postgres user and row-level security (Phase 6).

The SQL agent's queries never run as the app's own database user. They run as a second login,
SQL_AGENT_DB_USER, that:

- can SELECT a short list of tables (AGENT_TABLES) and nothing else: no INSERT/UPDATE/DELETE grants,
  `default_transaction_read_only = on`, and a `statement_timeout`;
- sees only the rows **row-level security** (RLS) lets through for the person asking. The policies call
  `lms_can_see_*()`, SQL functions generated from the permission matrix in app/permissions.py, so the
  rules are written once.

Who is asking? Before each query the app (as the owner) writes `(pid, user_id, role)` into
`sql_agent_scope`, keyed by the reader connection's backend process id. The policies look the caller up
with `pg_backend_pid()`, which a query can't fake. The usual trick, a setting such as
`SET app.user_id = 10`, can be changed by the query itself (`SELECT set_config('app.user_id', '1', true)`),
so a prompt-injected query could switch user. A row the reader can't even read can't be changed.

Note: this needs session-level connections; behind a transaction-pooling proxy (PgBouncer) the pid of the
reader changes between statements, so you'd pass the scope another way (e.g. a signed setting).

The table owner (the app's own user) bypasses RLS, so turning it on changes nothing for the rest of the app.
"""

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from app import models  # noqa: F401 - registers all tables on Base.metadata
from app.config import Settings, get_settings
from app.db import Base
from app.permissions import PERMISSIONS

SCOPE_TABLE = "sql_agent_scope"
POLICY = "sql_agent_read"


@dataclass(frozen=True)
class AgentTable:
    name: str
    rule: str  # the RLS policy: which rows the reader may see (SQL, evaluated per row)
    who: str  # the same rule in words (docs, the "what can I ask" panel)
    hidden: tuple[str, ...] = ()  # columns the reader can't select at all


# The only tables the agent can query. Everything else (documents, chunks, api_tokens, doubts, the
# audit logs...) has no grant, and the validator refuses it before Postgres would.
AGENT_TABLES: list[AgentTable] = [
    AgentTable("courses", "true", "everyone: the course catalogue"),
    AgentTable("modules", "true", "everyone: the course catalogue"),
    AgentTable("topics", "true", "everyone: the course catalogue"),
    AgentTable("quizzes", "true", "everyone: the course catalogue"),
    AgentTable(
        "users",
        "role <> 'student' OR lms_can_see_student('student_records', id)",
        "staff: everyone; students: by the student records scope",
    ),
    AgentTable(
        "enrollments",
        "lms_can_see_record('student_records', student_id, course_id)",
        "student records scope, per course",
    ),
    AgentTable(
        "quiz_attempts",
        "lms_can_see_record('student_records', student_id, (SELECT q.course_id FROM quizzes q WHERE q.id = quiz_id))",
        "student records scope, per course of the quiz",
    ),
    AgentTable("payments", "lms_can_see_record('payments', student_id, course_id)", "payments scope"),
    AgentTable("login_events", "lms_can_see_record('account_activity', user_id, NULL)", "account activity scope"),
    AgentTable(
        "tickets",
        "lms_can_see_record('tickets', student_id, course_id)",
        "tickets scope",
        hidden=("question_vec",),
    ),
    AgentTable("llm_usage", "lms_can_see_record('ai_usage', user_id, NULL)", "AI usage scope"),
]

TABLE_NAMES = frozenset(t.name for t in AGENT_TABLES)

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _role_name(settings: Settings) -> str:
    name = settings.sql_agent_db_user
    if not _IDENT.match(name):
        raise ValueError(f"SQL_AGENT_DB_USER must be a plain lower-case name, got {name!r}")
    return name


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def scope_case() -> str:
    """The permission matrix as one SQL CASE: 'student:payments' -> 'own'. Unknown -> 'none' (deny)."""
    whens = [
        f"WHEN '{role.value}:{resource.value}' THEN '{scope.value}'"
        for role, resources in PERMISSIONS.items()
        for resource, scope in resources.items()
    ]
    return "CASE lms_scope_role() || ':' || p_resource\n    " + "\n    ".join(whens) + "\n    ELSE 'none' END"


def _functions() -> list[str]:
    # SECURITY DEFINER: they run as the owner, so they can read sql_agent_scope, tickets and enrollments
    # without RLS (and without the reader having grants on them). search_path is pinned so a caller can't
    # swap in their own tables. STABLE: same answer for the whole query.
    definer = "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp"
    return [
        f"""CREATE OR REPLACE FUNCTION lms_scope_user() RETURNS integer {definer} AS $fn$
  SELECT user_id FROM {SCOPE_TABLE} WHERE pid = pg_backend_pid()
$fn$""",
        f"""CREATE OR REPLACE FUNCTION lms_scope_role() RETURNS text {definer} AS $fn$
  SELECT role FROM {SCOPE_TABLE} WHERE pid = pg_backend_pid()
$fn$""",
        f"""CREATE OR REPLACE FUNCTION lms_scope(p_resource text) RETURNS text {definer} AS $fn$
  SELECT {scope_case()}
$fn$""",
        # A student (as a person): may the caller see them at all?
        f"""CREATE OR REPLACE FUNCTION lms_can_see_student(p_resource text, p_student integer) RETURNS boolean
{definer} AS $fn$
  SELECT CASE lms_scope(p_resource)
    WHEN 'all' THEN true
    WHEN 'own' THEN p_student = lms_scope_user()
    WHEN 'own_courses' THEN EXISTS (
      SELECT 1 FROM enrollments e JOIN courses c ON c.id = e.course_id
      WHERE e.student_id = p_student AND c.teacher_id = lms_scope_user())
    WHEN 'ticket_student' THEN EXISTS (
      SELECT 1 FROM tickets t WHERE t.student_id = p_student AND t.status <> 'resolved')
    ELSE false END
$fn$""",
        # One record about a student in one course (null = not about a course): teachers only see
        # records of their own courses, not the same student's records in someone else's course.
        f"""CREATE OR REPLACE FUNCTION lms_can_see_record(p_resource text, p_student integer, p_course integer)
RETURNS boolean {definer} AS $fn$
  SELECT CASE lms_scope(p_resource)
    WHEN 'all' THEN true
    WHEN 'own' THEN p_student = lms_scope_user()
    WHEN 'own_courses' THEN EXISTS (SELECT 1 FROM courses c WHERE c.id = p_course AND c.teacher_id = lms_scope_user())
    WHEN 'ticket_student' THEN EXISTS (
      SELECT 1 FROM tickets t WHERE t.student_id = p_student AND t.status <> 'resolved')
    ELSE false END
$fn$""",
    ]


def setup_statements(settings: Settings | None = None) -> list[str]:
    """Idempotent DDL: safe to run on every start. Needs a database user that may create roles."""
    settings = settings or get_settings()
    reader = _role_name(settings)
    password = _literal(settings.sql_agent_db_password.get_secret_value())
    timeout = int(settings.sql_agent_timeout_ms)
    statements = [
        f"""DO $do$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{reader}') THEN CREATE ROLE {reader} LOGIN; END IF;
END $do$""",
        f"ALTER ROLE {reader} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS "
        f"CONNECTION LIMIT 10 PASSWORD {password}",
        # Defaults for every session of this user, in case a query ever runs outside our transaction.
        f"ALTER ROLE {reader} SET default_transaction_read_only = on",
        f"ALTER ROLE {reader} SET statement_timeout = {timeout}",
        f"""CREATE TABLE IF NOT EXISTS {SCOPE_TABLE} (
  pid integer PRIMARY KEY,
  user_id integer NOT NULL,
  role varchar(20) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now())""",
        f"COMMENT ON TABLE {SCOPE_TABLE} IS 'Who the SQL agent connection with this backend pid is answering "
        "for. Written by the app before each agent query; read by the row-level security policies.'",
        *_functions(),
        f"GRANT USAGE ON SCHEMA public TO {reader}",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {reader}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {reader}",
    ]
    for table in AGENT_TABLES:
        if table.hidden:
            columns = [c.name for c in Base.metadata.tables[table.name].columns if c.name not in table.hidden]
            statements.append(f"GRANT SELECT ({', '.join(columns)}) ON {table.name} TO {reader}")
        else:
            statements.append(f"GRANT SELECT ON {table.name} TO {reader}")
        statements += [
            f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {POLICY} ON {table.name}",
            f"CREATE POLICY {POLICY} ON {table.name} FOR SELECT TO {reader} USING ({table.rule})",
        ]
    return statements


async def setup_access(conn: AsyncConnection, settings: Settings | None = None) -> None:
    for statement in setup_statements(settings):
        # exec_driver_sql: the statements contain ':' (CASE keys), which text() would read as bind parameters.
        await conn.exec_driver_sql(statement)
