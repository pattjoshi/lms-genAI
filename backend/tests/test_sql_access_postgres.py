"""Phase 6, layer 3 against a real Postgres: the read-only user and row-level security hold even for SQL
that skipped the validator. Skipped when Postgres isn't running.

Works in its own throwaway database (lms_sql_agent_test, created and dropped here), never the app's data.
The read-only login itself is a cluster-wide role, so it is the same one the app uses.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import Base
from app.models import (
    Course,
    Enrollment,
    LLMUsage,
    LoginEvent,
    Module,
    Payment,
    Quiz,
    QuizAttempt,
    Role,
    Ticket,
    Topic,
    User,
)
from app.sql_agent import access, describe
from app.sql_agent.run import QueryFailed, run_scoped

TEST_DB = "lms_sql_agent_test"
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _url(database: str, reader: bool = False) -> str:
    s = get_settings()
    url = make_url(s.sql_agent_database_url if reader else s.database_url)
    return url.set(database=database).render_as_string(hide_password=False)


# people: 1 admin, 1 support, 2 teachers, 3 students
ADMIN, SUPPORT, T_DB, T_DL, RIYA, ARJUN, KARAN = 1, 2, 3, 4, 10, 11, 12
DB201, DL301 = 1, 2


def _rows() -> list[list]:
    def user(uid, name, role):
        return User(id=uid, full_name=name, email=f"{uid}@t.in", role=role, city="Pune", joined_at=NOW)

    users = [
        user(ADMIN, "Neha Admin", Role.admin),
        user(SUPPORT, "Rohan Support", Role.support),
        user(T_DB, "Rahul Teacher", Role.teacher),
        user(T_DL, "Suresh Teacher", Role.teacher),
        user(RIYA, "Riya Student", Role.student),
        user(ARJUN, "Arjun Student", Role.student),
        user(KARAN, "Karan Student", Role.student),
    ]
    courses = [
        Course(id=DB201, code="DB201", title="DBMS", description="", teacher_id=T_DB, price_inr=1, created_at=NOW),
        Course(id=DL301, code="DL301", title="DL", description="", teacher_id=T_DL, price_inr=1, created_at=NOW),
    ]
    modules = [Module(id=c, course_id=c, position=1, title="M1") for c in (DB201, DL301)]
    topics = [Topic(id=c, module_id=c, position=1, name=f"T{c}", difficulty="easy") for c in (DB201, DL301)]
    quizzes = [Quiz(id=c, topic_id=c, course_id=c, title=f"Q{c}", created_at=NOW) for c in (DB201, DL301)]

    def enroll(student, course):
        return Enrollment(student_id=student, course_id=course, enrolled_at=NOW, status="active", progress_pct=10)

    # Riya: DB201 + DL301; Arjun: DL301; Karan: DB201
    enrollments = [enroll(RIYA, DB201), enroll(RIYA, DL301), enroll(ARJUN, DL301), enroll(KARAN, DB201)]
    attempts = [
        QuizAttempt(quiz_id=q, student_id=s, attempted_at=NOW, score_pct=50, time_taken_sec=60)
        for s, q in [(RIYA, DB201), (RIYA, DL301), (ARJUN, DL301), (KARAN, DB201)]
    ]
    payments = [
        Payment(student_id=s, course_id=c, amount_inr=100, status="failed", method="upi", created_at=NOW)
        for s, c in [(RIYA, DB201), (ARJUN, DL301), (ARJUN, DL301), (KARAN, DB201)]
    ]
    logins = [LoginEvent(user_id=u, occurred_at=NOW, success=False, device="web") for u in (RIYA, ARJUN, KARAN, T_DB)]
    tickets = [  # support may see Karan's records (open ticket), not Arjun's (resolved)
        Ticket(student_id=KARAN, reason="support", category="login", subject="locked", status="open"),
        Ticket(student_id=ARJUN, reason="support", category="payment", subject="paid", status="resolved"),
    ]
    usage = [LLMUsage(user_id=RIYA, feature="x", model="m", status="success")]
    return [users, courses, modules, topics, quizzes, enrollments, attempts, payments, logins, tickets, usage]


async def _create() -> None:
    admin = create_async_engine(_url("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        await conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    await admin.dispose()
    owner = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    async with owner.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await access.setup_access(conn)
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(owner) as session:
        for rows in _rows():
            session.add_all(rows)
            await session.flush()
        await session.commit()
    await owner.dispose()


async def _drop() -> None:
    admin = create_async_engine(_url("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    await admin.dispose()


@pytest.fixture(scope="module", autouse=True)
def database():
    try:
        asyncio.run(_create())
    except (OSError, ConnectionError) as exc:
        pytest.skip(f"Postgres is not running: {exc}")
    except Exception as exc:  # noqa: BLE001 - e.g. a user without CREATEDB / CREATEROLE
        if "Connect call failed" in str(exc) or "connection refused" in str(exc).lower():
            pytest.skip(f"Postgres is not running: {exc}")
        raise
    yield
    asyncio.run(_drop())


@pytest.fixture
async def engines():
    owner = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    reader = create_async_engine(_url(TEST_DB, reader=True), poolclass=NullPool)
    yield owner, reader
    await owner.dispose()
    await reader.dispose()


def who(uid: int, role: Role) -> User:
    return User(id=uid, full_name="x", role=role, is_active=True)


async def ask(engines, user: User, sql: str, **kw):
    owner, reader = engines
    return await run_scoped(user, sql, owner=owner, reader=reader, **kw)


async def ids(engines, user: User, sql: str) -> list:
    return sorted(r[0] for r in (await ask(engines, user, sql)).rows)


# --- scope: the same query, a different answer per person ---------------------


@pytest.mark.parametrize(
    ("user", "payments", "students"),
    [
        (who(RIYA, Role.student), [RIYA], [RIYA]),  # own only
        (who(ARJUN, Role.student), [ARJUN, ARJUN], [ARJUN]),
        (who(T_DB, Role.teacher), [], [KARAN, RIYA]),  # no payments; students of DB201 only
        (who(T_DL, Role.teacher), [], [ARJUN, RIYA]),
        (who(SUPPORT, Role.support), [KARAN], [KARAN]),  # only the open ticket's student
        (who(ADMIN, Role.admin), [ARJUN, ARJUN, RIYA, KARAN], [ARJUN, RIYA, KARAN]),
    ],
)
async def test_each_role_sees_only_its_rows(engines, user, payments, students):
    assert await ids(engines, user, "SELECT student_id FROM payments") == sorted(payments)
    assert await ids(engines, user, "SELECT id FROM users WHERE role = 'student'") == sorted(students)
    staff = await ids(engines, user, "SELECT id FROM users WHERE role <> 'student'")
    assert staff == [ADMIN, SUPPORT, T_DB, T_DL]  # staff names are visible to everyone


async def test_a_teacher_sees_a_shared_student_only_in_their_own_course(engines):
    # Riya takes both courses; Rahul (DB201) must not see her DL301 attempt or enrollment
    rahul = who(T_DB, Role.teacher)
    sql = "SELECT q.course_id, a.student_id FROM quiz_attempts a JOIN quizzes q ON q.id = a.quiz_id"
    rows = (await ask(engines, rahul, sql)).rows
    assert sorted(rows) == [(DB201, RIYA), (DB201, KARAN)]
    assert await ids(engines, rahul, "SELECT course_id FROM enrollments") == [DB201, DB201]
    assert await ids(engines, rahul, "SELECT user_id FROM login_events") == []  # no account activity


async def test_tickets_and_ai_usage(engines):
    assert len((await ask(engines, who(SUPPORT, Role.support), "SELECT id FROM tickets")).rows) == 2
    assert await ids(engines, who(ARJUN, Role.student), "SELECT student_id FROM tickets") == [ARJUN]
    assert await ids(engines, who(T_DB, Role.teacher), "SELECT id FROM tickets") == []
    assert len((await ask(engines, who(ADMIN, Role.admin), "SELECT id FROM llm_usage")).rows) == 1
    assert await ids(engines, who(RIYA, Role.student), "SELECT id FROM llm_usage") == []


async def test_filtering_by_someone_elses_id_returns_nothing(engines):
    # A03: "what did Ananya score?" -> the model may write the right SQL; the database returns no rows
    sql = f"SELECT score_pct FROM quiz_attempts WHERE student_id = {ARJUN}"
    assert (await ask(engines, who(RIYA, Role.student), sql)).rows == []


# --- read-only: these never pass the validator, and fail in Postgres too -------


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM payments",
        "UPDATE users SET role = 'admin' WHERE id = 10",
        "INSERT INTO sql_agent_scope VALUES (pg_backend_pid(), 1, 'admin')",
        "SELECT * FROM sql_agent_scope",
        "SELECT * FROM api_tokens",
        "SELECT question_vec FROM tickets",
        "WITH x AS (DELETE FROM payments RETURNING id) SELECT * FROM x",
        "SELECT set_config('role', 'lms', false)",
    ],
)
async def test_layer_3_holds_without_the_validator(engines, sql):
    with pytest.raises(QueryFailed):
        await ask(engines, who(ADMIN, Role.admin), sql)
    owner, _ = engines
    async with owner.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM payments")) == 4  # nothing was deleted


async def test_the_reader_cannot_write_even_outside_our_transaction(engines):
    # The wrapper and the validator make the tests above fail early; this goes straight to the login.
    from sqlalchemy.exc import DBAPIError

    _, reader = engines
    async with reader.connect() as conn:
        with pytest.raises(DBAPIError, match="read-only transaction"):  # the role's default
            await conn.execute(text("DELETE FROM payments"))
    async with reader.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ WRITE"))
        with pytest.raises(DBAPIError, match="permission denied"):  # and no grant to write anyway
            await conn.execute(text("DELETE FROM payments"))
    async with reader.connect() as conn:
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text("SET ROLE lms"))


async def test_changing_settings_cannot_change_who_is_asking(engines):
    # The classic RLS mistake is "WHERE student_id = current_setting('app.user_id')": a query can set it.
    sql = "SELECT set_config('app.user_id', '1', true) AS s, student_id FROM payments"
    rows = (await ask(engines, who(RIYA, Role.student), sql)).rows
    assert [r[1] for r in rows] == [RIYA]


async def test_sql_goes_to_postgres_as_written(engines):
    # '%' and ':' mean something to DB-API parameter styles; the model's SQL must reach Postgres untouched
    sql = "SELECT full_name, '10:30' AS t, 5 % 3 AS m FROM users WHERE full_name ILIKE '%riya%' -- trailing"
    assert (await ask(engines, who(RIYA, Role.student), sql)).rows == [("Riya Student", "10:30", 2)]


async def test_time_and_row_limits(engines, monkeypatch):
    monkeypatch.setattr(get_settings(), "sql_agent_timeout_ms", 200)
    with pytest.raises(QueryFailed) as err:
        await ask(engines, who(ADMIN, Role.admin), "SELECT pg_sleep(2)")
    assert err.value.stage == "timeout"
    result = await ask(engines, who(ADMIN, Role.admin), "SELECT id FROM users ORDER BY id", max_rows=3)
    assert [r[0] for r in result.rows] == [ADMIN, SUPPORT, T_DB] and result.truncated


async def test_no_scope_row_means_no_rows_and_rows_are_cleaned_up(engines):
    owner, reader = engines
    await ask(engines, who(RIYA, Role.student), "SELECT 1")
    async with owner.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM sql_agent_scope")) == 0
    async with reader.connect() as conn:  # connected, but nobody registered this pid
        assert await conn.scalar(text("SELECT count(*) FROM payments")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM users WHERE role = 'student'")) == 0
        assert await conn.scalar(text("SHOW transaction_read_only")) == "on"


async def test_schema_description_comes_from_postgres(engines, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    owner, _ = engines
    async with AsyncSession(owner) as session:
        schema = await describe.schema_text(session, refresh=True)
    assert "### quiz_attempts: A student's attempt at a quiz" in schema
    assert "- quiz_id integer -> quizzes.id" in schema
    assert "score_pct integer: 0-100. Below 50 counts as failed." in schema
    assert "question_vec" not in schema and "api_tokens" not in schema
    describe._cache = None
