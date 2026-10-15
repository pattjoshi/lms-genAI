"""Open tickets for chat messages saved before Phase 5 (unanswered questions and support messages).

    uv run python -m app.tickets.backfill            # last 30 days
    uv run python -m app.tickets.backfill --days 90

Safe to run twice: a message that already has a ticket is skipped. No AI calls.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Doubt, Ticket
from app.tickets import service


async def main(days: int) -> None:
    since = datetime.now(UTC) - timedelta(days=days)
    opened = 0
    async with SessionLocal() as session:
        has_ticket = select(Ticket.doubt_id).where(Ticket.doubt_id.is_not(None))
        doubts = (
            await session.scalars(
                select(Doubt).where(Doubt.created_at >= since, Doubt.id.not_in(has_ticket)).order_by(Doubt.id)
            )
        ).all()
        for doubt in doubts:
            reason = service.auto_reason(doubt)
            if reason:
                await service.open_for_doubt(session, doubt, reason)
                opened += 1
        await session.commit()
    print(f"Looked at {len(doubts)} messages from the last {days} days, opened {opened} tickets.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30)
    asyncio.run(main(parser.parse_args().days))
