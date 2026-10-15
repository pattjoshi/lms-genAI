"""Login and payment problems (Phase 4, S18): answered from the student's OWN records, no LLM.

The reply is a template filled with facts (the last failed logins, the last payments), so it can't
invent a refund policy or promise something support won't do. Every support message is saved with
intent "support"; Phase 5 turns them into tickets for the support team.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, LoginEvent, Payment, PaymentStatus, User

LOGIN_WORDS = ("log in", "login", "log-in", "sign in", "signin", "password", "otp", "locked", "account")

ADVICE = {
    "wrong_password": "Use “Forgot password” on the login page to set a new one.",
    "account_locked": "Your account locks after several wrong passwords. It unlocks by itself after 30 minutes, "
    "or support can unlock it now.",
    "otp_expired": "OTP codes expire after 5 minutes. Ask for a new code and enter it straight away.",
}


def _ago(at: datetime, now: datetime) -> str:
    hours = (now - at).total_seconds() / 3600
    if hours < 1:
        return "less than an hour ago"
    if hours < 48:
        return f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
    return f"{int(hours // 24)} days ago"


def is_login_problem(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in LOGIN_WORDS) and "payment" not in t and "refund" not in t


def login_reply(events: list[LoginEvent], now: datetime) -> tuple[str, dict]:
    recent = [e for e in events if e.occurred_at >= now - timedelta(days=7)]
    failed = [e for e in recent if not e.success]
    if not failed:
        return (
            "I don't see any failed logins on your account in the last 7 days, so the account itself looks fine. "
            "If a page keeps sending you back to the login, sign out, clear the site's cookies and sign in again.",
            {"failed_logins": 0},
        )
    last = failed[0]
    reasons = sorted({e.failure_reason or "unknown" for e in failed})
    reason = (last.failure_reason or "unknown").replace("_", " ")
    text = (
        f"I see {len(failed)} failed login{'s' if len(failed) > 1 else ''} in the last 7 days, the last one "
        f"{_ago(last.occurred_at, now)} on {last.device} (reason: {reason})."
    )
    tips = [ADVICE[r] for r in reasons if r in ADVICE]
    if tips:
        text += "\n\n" + "\n".join(f"• {t}" for t in tips)
    return text, {"failed_logins": len(failed), "reasons": reasons, "last_device": last.device}


def payment_reply(payments: list[tuple[Payment, str]], now: datetime) -> tuple[str, dict]:
    if not payments:
        text = (
            "I don't see any payments on your account. If money left your bank, keep the bank's reference number "
            "for support."
        )
        return text, {"payments": 0}
    lines = []
    for p, code in payments[:5]:
        status = p.status.value
        why = f" ({p.failure_reason})" if p.failure_reason else ""
        lines.append(f"• {code}: ₹{p.amount_inr} by {p.method.value}, {status}{why}, {_ago(p.created_at, now)}")
    text = "Your most recent payments:\n" + "\n".join(lines)
    bad = [p for p, _ in payments if p.status in (PaymentStatus.failed, PaymentStatus.pending)]
    if bad:
        text += (
            "\n\nA failed payment is not charged; if your bank shows a debit for it, it is reversed by the bank, "
            "usually within 5-7 working days. A pending payment settles or fails on its own within 24 hours."
        )
    return text, {"payments": len(payments), "failed_or_pending": len(bad)}


async def answer(session: AsyncSession, user: User, text: str) -> tuple[str, dict]:
    now = datetime.now(UTC)
    if is_login_problem(text):
        events = (
            await session.scalars(
                select(LoginEvent)
                .where(LoginEvent.user_id == user.id)  # scope: OWN
                .order_by(LoginEvent.occurred_at.desc())
                .limit(20)
            )
        ).all()
        reply, facts = login_reply(list(events), now)
        kind = "login"
    else:
        rows = (
            await session.execute(
                select(Payment, Course.code)
                .join(Course, Course.id == Payment.course_id)
                .where(Payment.student_id == user.id)  # scope: OWN
                .order_by(Payment.created_at.desc())
                .limit(5)
            )
        ).all()
        reply, facts = payment_reply([(p, c) for p, c in rows], now)
        kind = "payment"
    reply += "\n\nI've saved this message for the support team. (The ticket queue they work from arrives in Phase 5.)"
    return reply, {"kind": kind, **facts}
