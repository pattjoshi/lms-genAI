"""Sign-in and authorization: passwords, sessions, roles, Google tokens, the CSRF guard.

The API tests run against a throwaway Postgres database (lms_auth_test, created and dropped here) and
are skipped when Postgres isn't running. The password, lockout and Google token tests need nothing.
"""

import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.accounts import google, limits
from app.accounts.passwords import hash_password, password_problem, verify_password
from app.config import get_settings
from app.db import Base, get_session
from app.main import app
from app.models import AuthSession, LoginEvent, Role, User

TEST_DB = "lms_auth_test"
NOW = datetime(2026, 10, 1, tzinfo=UTC)
ORIGIN = get_settings().frontend_origin
COOKIE = get_settings().auth_cookie_name


# --- No database needed ---


def test_password_hash_round_trip_and_salt():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2  # random salt per password
    assert h1.startswith("scrypt$")
    assert verify_password("correct horse battery", h1)
    assert not verify_password("correct horse batterY", h1)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "garbage")


def test_password_rules():
    assert password_problem("short") is not None
    assert password_problem("password123") is not None  # common
    assert password_problem("aaaaaaaaaa") is not None  # too few different characters
    assert password_problem("riyasharma-2026", "riyasharma@x.in") is not None  # contains the email
    assert password_problem("blue tram over the river") is None


def test_lockout_after_too_many_failures(monkeypatch):
    limits.reset_all()
    monkeypatch.setattr(get_settings(), "auth_max_failed_logins", 3)
    for _ in range(3):
        assert limits.retry_after("a@x.in", "1.1.1.1") == 0
        limits.record_failure("a@x.in", "1.1.1.1")
    assert limits.retry_after("a@x.in", "1.1.1.1") > 0
    assert limits.retry_after("b@x.in", "2.2.2.2") == 0  # other people are not affected
    limits.clear("a@x.in")
    assert limits.retry_after("a@x.in", None) == 0
    limits.reset_all()


@pytest.fixture
def google_keys(monkeypatch):
    """Sign ID tokens with our own key instead of Google's."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(get_settings(), "google_client_id", "our-client.apps.googleusercontent.com")
    monkeypatch.setattr(google._jwks, "get_signing_key_from_jwt", lambda _t: SimpleNamespace(key=key.public_key()))

    def sign(**overrides):
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "our-client.apps.googleusercontent.com",
            "sub": "google-123",
            "email": "Meera.Iyer@gmail.com",
            "email_verified": True,
            "name": "Meera Iyer",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        } | overrides
        return jwt.encode(claims, key, algorithm="RS256")

    return sign


async def test_google_token_checks(google_keys):
    account = await google.verify_credential(google_keys())
    assert (account.sub, account.email, account.name) == ("google-123", "meera.iyer@gmail.com", "Meera Iyer")
    for bad in (
        {"aud": "someone-elses-client"},
        {"iss": "https://evil.example"},
        {"email_verified": False},
        {"exp": int(time.time()) - 3600},
    ):
        with pytest.raises(google.GoogleTokenError):
            await google.verify_credential(google_keys(**bad))


# --- API against a throwaway database ---


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
        await conn.execute(
            text(
                "INSERT INTO users (id, full_name, email, role, city, joined_at, is_active) VALUES "
                "(1, 'Demo Admin', 'admin@lmsdemo.in', 'admin', 'Pune', :now, true), "
                "(2, 'Demo Teacher', 'teacher@lmsdemo.in', 'teacher', 'Pune', :now, true)"
            ),
            {"now": NOW},
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
async def db(database):
    engine = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override
    limits.reset_all()
    yield maker
    app.dependency_overrides.clear()
    await engine.dispose()


def _client() -> httpx.AsyncClient:
    # Requests from the browser carry the frontend's Origin; ASGITransport skips the app's startup work.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"Origin": ORIGIN}
    )


async def test_signup_login_me_logout(db):
    async with _client() as c:
        assert (await c.get("/auth/me")).status_code == 401

        weak = await c.post("/auth/signup", json={"full_name": "Asha Rao", "email": "asha@x.in", "password": "123"})
        assert weak.status_code == 400

        r = await c.post(
            "/auth/signup", json={"full_name": "Asha Rao", "email": " Asha@X.in ", "password": "blue tram river"}
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "student"  # sign-up never makes staff
        assert "httponly" in r.headers["set-cookie"].lower()
        me = (await c.get("/auth/me")).json()
        assert me["email"] == "asha@x.in" and me["has_password"] is True

        dup = await c.post(
            "/auth/signup", json={"full_name": "Asha Two", "email": "asha@x.in", "password": "blue tram river"}
        )
        assert dup.status_code == 409

        assert (await c.post("/auth/logout")).status_code == 204
        assert (await c.get("/auth/me")).status_code == 401

        wrong = await c.post("/auth/login", json={"email": "asha@x.in", "password": "nope nope nope"})
        assert wrong.status_code == 401
        unknown = await c.post("/auth/login", json={"email": "nobody@x.in", "password": "nope nope nope"})
        assert unknown.json()["message"] == wrong.json()["message"]  # doesn't reveal which emails exist

        ok = await c.post("/auth/login", json={"email": "ASHA@x.in", "password": "blue tram river"})
        assert ok.status_code == 200
        assert (await c.get("/auth/me")).json()["full_name"] == "Asha Rao"

    async with db() as s:
        user = await s.scalar(select(User).where(User.email == "asha@x.in"))
        events = (await s.scalars(select(LoginEvent).where(LoginEvent.user_id == user.id))).all()
        assert [e.success for e in events].count(False) == 1  # the wrong password is in the login history
        assert any(e.failure_reason == "wrong_password" for e in events)


async def test_lockout_returns_429(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_max_failed_logins", 2)
    async with _client() as c:
        await c.post("/auth/signup", json={"full_name": "Lock Me", "email": "lock@x.in", "password": "blue tram river"})
        for _ in range(2):
            await c.post("/auth/login", json={"email": "lock@x.in", "password": "wrong wrong"})
        r = await c.post("/auth/login", json={"email": "lock@x.in", "password": "blue tram river"})
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


async def test_roles_are_enforced_by_the_backend(db):
    async with _client() as c:
        await c.post("/auth/signup", json={"full_name": "Stu Dent", "email": "stu@x.in", "password": "blue tram river"})
        assert (await c.get("/admin/users")).status_code == 403
        assert (await c.get("/portal/admin/summary")).status_code == 403
        assert (await c.post("/auth/demo-login", json={"user_id": 1})).status_code in (200, 404)  # dev-only


async def test_admin_manages_users_and_deactivation_ends_sessions(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "dev")
    monkeypatch.setattr(get_settings(), "auth_demo_login", True)
    async with _client() as admin, _client() as teacher_client:
        assert (await admin.post("/auth/demo-login", json={"user_id": 1})).status_code == 200
        r = await admin.post(
            "/admin/users",
            json={"full_name": "New Teacher", "email": "nt@x.in", "role": "teacher", "password": "blue tram river"},
        )
        assert r.status_code == 201 and r.json()["role"] == "teacher"
        new_id = r.json()["id"]

        assert (
            await teacher_client.post("/auth/login", json={"email": "nt@x.in", "password": "blue tram river"})
        ).is_success
        assert (await teacher_client.get("/auth/me")).json()["role"] == "teacher"

        # Can't lock yourself out
        assert (await admin.patch("/admin/users/1", json={"role": "student"})).status_code == 400
        assert (await admin.patch("/admin/users/1", json={"is_active": False})).status_code == 400

        assert (await admin.patch(f"/admin/users/{new_id}", json={"is_active": False})).status_code == 200
        assert (await teacher_client.get("/auth/me")).status_code == 401  # signed out at once

        listing = (await admin.get("/admin/users", params={"q": "teacher"})).json()
        assert {u["email"] for u in listing["users"]} >= {"nt@x.in", "teacher@lmsdemo.in"}


async def test_demo_login_is_off_outside_dev(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    async with _client() as c:
        assert (await c.get("/auth/users")).status_code == 404
        assert (await c.post("/auth/demo-login", json={"user_id": 1})).status_code == 404
        assert (await c.get("/auth/config")).json()["demo_login"] is False


async def test_google_sign_in_creates_then_links(db, google_keys):
    async with _client() as c:
        r = await c.post("/auth/google", json={"credential": google_keys()})
        assert r.status_code == 200, r.text
        assert r.json()["created"] is True and r.json()["role"] == "student"
        me = (await c.get("/auth/me")).json()
        assert me["google_linked"] is True and me["has_password"] is False

        # A Google account whose verified email matches an existing user is linked, not duplicated.
        r = await c.post(
            "/auth/google", json={"credential": google_keys(sub="google-teacher", email="teacher@lmsdemo.in")}
        )
        assert r.json()["created"] is False and r.json()["id"] == 2

        forged = await c.post("/auth/google", json={"credential": google_keys(aud="another-app")})
        assert forged.status_code == 401


async def test_password_change_signs_out_other_browsers(db):
    async with _client() as a, _client() as b:
        await a.post("/auth/signup", json={"full_name": "Two Tabs", "email": "two@x.in", "password": "blue tram river"})
        await b.post("/auth/login", json={"email": "two@x.in", "password": "blue tram river"})
        r = await a.post(
            "/auth/password", json={"current_password": "blue tram river", "new_password": "green bus to the hills"}
        )
        assert r.status_code == 204
        assert (await a.get("/auth/me")).status_code == 200
        assert (await b.get("/auth/me")).status_code == 401
    async with db() as s:
        revoked = await s.scalar(select(AuthSession).where(AuthSession.revoked_at.is_not(None)))
        assert revoked is not None


async def test_cross_site_writes_are_refused(db):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"Origin": "https://evil.example"}
    ) as c:
        r = await c.post("/auth/login", json={"email": "asha@x.in", "password": "blue tram river"})
        assert r.status_code == 403 and r.json()["error"] == "bad_origin"


async def test_public_catalog_needs_no_login(db):
    async with _client() as c:
        r = await c.get("/public/stats")
        assert r.status_code == 200 and r.json()["instructors"] >= 1
        assert (await c.get("/public/catalog")).json()["courses"] == []


def test_role_enum_is_unchanged():
    assert {r.value for r in Role} == {"student", "teacher", "admin", "support"}
