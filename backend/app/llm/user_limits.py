"""Per-user limits on AI requests: at most AI_REQUESTS_PER_MINUTE and AI_REQUESTS_PER_DAY for each person.

Without them one account, or a script behind it, could use the whole DAILY_BUDGET_USD and the AI would stop
for every student until midnight. (The per-student spend cap is in app/llm/budget.py.)

The count lives in Postgres (`ai_requests`), not in memory, so it holds with several server processes. A
transaction-scoped advisory lock per user makes "count, then record" one step: ten requests sent at the same
moment are counted one after another, so they can't all slip under the limit together.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.budget import start_of_today
from app.models import AiRequest, User

LOCK_SPACE = 7301  # first key of pg_advisory_xact_lock(int, int): this module's locks; the second is the user id
KEEP = timedelta(days=2)  # older rows are no longer counted and are removed as the user makes new requests


def _refuse(message: str, retry_after: float) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS, message, headers={"Retry-After": str(max(1, int(retry_after) + 1))}
    )


async def check_and_record(session: AsyncSession, user: User, kind: str) -> None:
    """Record one AI request for `user`, or raise 429 (with Retry-After) if a limit is reached. Commits."""
    s = get_settings()
    if s.ai_requests_per_minute <= 0 and s.ai_requests_per_day <= 0:
        return
    now = datetime.now(UTC)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:space, :user_id)"), {"space": LOCK_SPACE, "user_id": user.id}
    )
    mine = AiRequest.user_id == user.id

    if s.ai_requests_per_minute > 0:
        window = now - timedelta(minutes=1)
        recent = (
            await session.scalars(
                select(AiRequest.created_at)
                .where(mine, AiRequest.created_at > window)
                .order_by(AiRequest.created_at.desc())
                .limit(s.ai_requests_per_minute)
            )
        ).all()
        if len(recent) >= s.ai_requests_per_minute:
            await session.rollback()  # releases the lock
            wait = (recent[-1] + timedelta(minutes=1) - now).total_seconds()
            raise _refuse("You're sending messages too fast. Wait a moment and try again.", wait)

    if s.ai_requests_per_day > 0:
        midnight = start_of_today(s)
        today = await session.scalar(select(func.count()).where(mine, AiRequest.created_at >= midnight))
        if today >= s.ai_requests_per_day:
            await session.rollback()
            wait = (midnight + timedelta(days=1) - now).total_seconds()
            raise _refuse(
                f"You've reached today's limit of {s.ai_requests_per_day} AI messages. It resets at midnight.", wait
            )

    session.add(AiRequest(user_id=user.id, kind=kind, created_at=now))
    await session.execute(delete(AiRequest).where(mine, AiRequest.created_at < now - KEEP))
    await session.commit()  # releases the lock
