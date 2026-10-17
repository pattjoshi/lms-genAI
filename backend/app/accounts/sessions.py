"""Login sessions: a random id in an httpOnly cookie, its SHA-256 hash in `auth_sessions`.

Why not a JWT? A JWT can't be taken back before it expires; a row in the database can. Logging out,
"sign out everywhere", changing a password or an admin deactivating someone ends their sessions at
once. The lookup is one indexed query per request, which this app makes anyway to load the user.

httpOnly: page JavaScript (and so an XSS bug) can't read the cookie. SameSite=Lax: other sites can't
make the browser send it with a form post. The Origin check in app/main.py covers the rest.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AuthSession, User


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def start(session: AsyncSession, user: User, method: str, user_agent: str | None) -> str:
    """Create a session row and return the raw token (it only ever leaves the server in the cookie)."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=_hash(token),
            method=method,
            user_agent=(user_agent or "")[:200] or None,
            created_at=now,
            expires_at=now + timedelta(days=get_settings().auth_session_days),
        )
    )
    await session.flush()
    return token


async def user_for(session: AsyncSession, token: str | None) -> User | None:
    """The active user behind a cookie, or None (unknown, expired, revoked, or the user was deactivated)."""
    if not token:
        return None
    row = await session.scalar(select(AuthSession).where(AuthSession.token_hash == _hash(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        return None
    user = await session.get(User, row.user_id)
    return user if user is not None and user.is_active else None


async def end(session: AsyncSession, token: str | None) -> None:
    if token:
        await session.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == _hash(token), AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )


async def end_all(session: AsyncSession, user_id: int, keep_token: str | None = None) -> None:
    """Sign a user out everywhere (password changed, role changed, deactivated), optionally keeping this browser."""
    query = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if keep_token:
        query = query.where(AuthSession.token_hash != _hash(keep_token))
    await session.execute(query.values(revoked_at=datetime.now(UTC)))


def set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.auth_cookie_name,
        token,
        max_age=s.auth_session_days * 86400,
        httponly=True,
        secure=s.auth_cookie_secure or s.auth_cookie_samesite == "none",  # browsers reject SameSite=None without it
        samesite=s.auth_cookie_samesite,
        path="/",
    )


def clear_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        s.auth_cookie_name,
        path="/",
        httponly=True,
        secure=s.auth_cookie_secure or s.auth_cookie_samesite == "none",
        samesite=s.auth_cookie_samesite,
    )
