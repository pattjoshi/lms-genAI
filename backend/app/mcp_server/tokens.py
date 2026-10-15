"""Personal access tokens (M2): how an MCP client proves who it is acting for.

A token is a long random string shown ONCE when it is created. The database keeps only its SHA-256
hash, so a leaked database backup can't be used to call the server, and the user revokes a token
without changing anything else. A token carries no permissions of its own: it IS its user, and every
tool call goes through that user's role in the permission matrix (app/permissions.py).

SHA-256 (not bcrypt) is fine here because the token is 256 random bits, not a password a person
chose: there is nothing to brute-force, and a fast hash lets us look the token up by its hash.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiToken, User

PREFIX = "lms_"


def new_token() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Identity:
    """Who an MCP request acts for, and how it reached us."""

    user: User
    via: str  # http | stdio | agent
    token_id: int | None = None

    @property
    def limit_key(self) -> str:
        return f"token:{self.token_id}" if self.token_id else f"user:{self.user.id}:{self.via}"


async def create(session: AsyncSession, user: User, name: str) -> tuple[ApiToken, str]:
    token = new_token()
    name = name.strip()[:80] or "MCP client"
    row = ApiToken(user_id=user.id, name=name, prefix=token[:10], token_hash=hash_token(token))
    session.add(row)
    await session.flush()
    return row, token


async def verify(session: AsyncSession, token: str) -> Identity | None:
    """The user behind a token, or None if it is unknown, revoked, or its user is inactive."""
    if not token.startswith(PREFIX):
        return None
    row = await session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None:
        return None
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    await session.execute(update(ApiToken).where(ApiToken.id == row.id).values(last_used_at=datetime.now(UTC)))
    await session.commit()
    return Identity(user=user, via="http", token_id=row.id)
