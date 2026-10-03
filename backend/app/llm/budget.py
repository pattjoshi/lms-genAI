"""Cost tracking and the daily budget guard.

Every LLM call writes one `llm_usage` row (success or error). Before each call we sum
today's cost; if it reached DAILY_BUDGET_USD, the call is refused.

Cost = input_tokens * input_price + output_tokens * output_price  (prices per 1M tokens)

Note: the check happens BEFORE a call and we only know the cost AFTER it, so a few
parallel requests can overshoot the limit by a few cents. Fine for a safety net;
OpenAI's own monthly limit is the hard stop.
"""

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.errors import DailyBudgetExceededError
from app.models import LLMUsage

log = logging.getLogger(__name__)


def chat_cost_usd(input_tokens: int, output_tokens: int, settings: Settings) -> float:
    return (
        input_tokens * settings.chat_price_input_per_1m + output_tokens * settings.chat_price_output_per_1m
    ) / 1_000_000


def embedding_cost_usd(tokens: int, settings: Settings) -> float:
    return tokens * settings.embedding_price_per_1m / 1_000_000


def start_of_today(settings: Settings) -> datetime:
    tz = ZoneInfo(settings.app_timezone)
    return datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)


async def spent_today_usd(session: AsyncSession, settings: Settings) -> float:
    total = await session.scalar(
        select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(LLMUsage.created_at >= start_of_today(settings))
    )
    return float(total or 0.0)


async def ensure_budget_available(session: AsyncSession, settings: Settings) -> None:
    spent = await spent_today_usd(session, settings)
    if spent >= settings.daily_budget_usd:
        raise DailyBudgetExceededError(
            f"Daily AI budget reached (${spent:.4f} of ${settings.daily_budget_usd:.2f}). "
            "It resets at midnight, or raise DAILY_BUDGET_USD in .env.",
            code="daily_budget_reached",
        )


async def record_usage(session: AsyncSession, **fields) -> None:
    """Write one usage row. Never let bookkeeping break the user's request."""
    try:
        session.add(LLMUsage(**fields))
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
        log.exception("Could not record LLM usage row")
