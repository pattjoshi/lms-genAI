"""Per-user AI limits: requests per minute and per day, and the per-student daily spend.

Runs against a throwaway Postgres database (lms_limits_test, created and dropped here); skipped when Postgres
isn't running.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.accounts import limits as login_limits
from app.config import get_settings
from app.db import Base, get_session
from app.llm import user_limits
from app.llm.budget import ensure_budget_available
from app.llm.errors import DailyBudgetExceededError
from app.main import app
from app.models import AiRequest, LLMUsage, Role, User

TEST_DB = "lms_limits_test"


def _url(database: str) -> str:
    return make_url(get_settings().database_url).set(database=database).render_as_string(hide_password=False)


async def _create() -> None:
    admin = create_async_engine(_url("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        await conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    await admin.dispose()
    owner = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    async with owner.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        now = datetime.now(UTC)
        for user_id, role in ((1, "student"), (2, "teacher"), (3, "student")):
            await conn.execute(
                text(
                    "INSERT INTO users (id, full_name, email, role, city, joined_at, is_active) "
                    "VALUES (:id, 'User', :email, :role, 'Pune', :now, true)"
                ),
                {"id": user_id, "email": f"u{user_id}@x.in", "role": role, "now": now},
            )
        await conn.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), 10)"))
    await owner.dispose()


async def _drop() -> None:
    admin = create_async_engine(_url("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    await admin.dispose()


@pytest.fixture(scope="module")
def database():
    try:
        asyncio.run(_create())
    except (OSError, ConnectionError) as exc:
        pytest.skip(f"Postgres is not running: {exc}")
    except Exception as exc:  # noqa: BLE001
        if "Connect call failed" in str(exc) or "connection refused" in str(exc).lower():
            pytest.skip(f"Postgres is not running: {exc}")
        raise
    yield
    asyncio.run(_drop())


@pytest.fixture
async def maker(database, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_requests_per_minute", 3)
    monkeypatch.setattr(get_settings(), "ai_requests_per_day", 5)
    monkeypatch.setattr(get_settings(), "student_daily_budget_usd", 0.10)
    engine = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await session.execute(text("TRUNCATE ai_requests, llm_usage"))
        await session.commit()

    async def override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override
    login_limits.reset_all()
    yield maker
    app.dependency_overrides.clear()
    await engine.dispose()


async def _record(maker, user_id: int) -> HTTPException | None:
    async with maker() as session:
        user = await session.get(User, user_id)
        try:
            await user_limits.check_and_record(session, user, "chat")
        except HTTPException as exc:
            return exc
    return None


async def _add_requests(maker, user_id: int, *ages: timedelta) -> None:
    now = datetime.now(UTC)
    async with maker() as session:
        session.add_all(AiRequest(user_id=user_id, kind="chat", created_at=now - age) for age in ages)
        await session.commit()


async def test_per_minute_limit(maker):
    for _ in range(3):
        assert await _record(maker, 1) is None
    refused = await _record(maker, 1)
    assert refused is not None and refused.status_code == 429
    assert 1 <= int(refused.headers["Retry-After"]) <= 61
    assert await _record(maker, 2) is None  # another person isn't affected


async def test_per_day_limit_counts_only_today(maker, monkeypatch):
    monkeypatch.setattr(user_limits, "start_of_today", lambda _: datetime.now(UTC) - timedelta(hours=1))
    await _add_requests(maker, 1, timedelta(days=3))  # yesterday or before: not counted
    await _add_requests(maker, 1, *[timedelta(minutes=2)] * 4)  # today, outside the minute window
    assert await _record(maker, 1) is None  # the 5th today is allowed, and old rows are cleaned up
    refused = await _record(maker, 1)
    assert refused is not None and refused.status_code == 429 and "today's limit" in refused.detail
    async with maker() as session:
        assert await session.scalar(text("SELECT count(*) FROM ai_requests WHERE user_id = 1")) == 5


async def test_zero_turns_the_limits_off(maker, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_requests_per_minute", 0)
    monkeypatch.setattr(get_settings(), "ai_requests_per_day", 0)
    for _ in range(6):
        assert await _record(maker, 1) is None


async def test_parallel_requests_cannot_all_slip_through(maker):
    results = await asyncio.gather(*(_record(maker, 3) for _ in range(10)))
    assert sum(r is None for r in results) == 3


async def test_student_daily_spend_cap(maker):
    async with maker() as session:
        for user_id in (1, 2):
            session.add(LLMUsage(user_id=user_id, feature="doubt_answer", model="m", cost_usd=0.11, status="success"))
        await session.commit()
        student, teacher = await session.get(User, 1), await session.get(User, 2)
        assert student.role == Role.student and teacher.role == Role.teacher
        with pytest.raises(DailyBudgetExceededError) as caught:
            await ensure_budget_available(session, get_settings(), student)
        assert caught.value.code == "user_budget_reached"
        await ensure_budget_available(session, get_settings(), teacher)  # staff: only the shared budget
        await ensure_budget_available(session, get_settings(), await session.get(User, 3))  # another student


async def test_api_answers_429_before_calling_the_ai(maker, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_requests_per_minute", 1)
    monkeypatch.setattr(get_settings(), "auth_signup_open", True)
    origin = get_settings().frontend_origin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"Origin": origin}
    ) as c:
        r = await c.post(
            "/auth/signup", json={"full_name": "Fast Typer", "email": "fast@x.in", "password": "blue tram river"}
        )
        assert r.status_code == 201, r.text
        await _add_requests(maker, r.json()["id"], timedelta(seconds=1))
        for path, body in (("/ai/hello", {"message": "hi"}), ("/chat/ask", {"question": "what is a join?"})):
            refused = await c.post(path, json=body)
            assert refused.status_code == 429, (path, refused.text)
            assert "Retry-After" in refused.headers
            assert refused.json()["error"] == "http_429"
