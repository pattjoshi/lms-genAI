"""Accounts: create users, check passwords, sign in with Google, record every attempt.

Every sign-in attempt, good or bad, is written to `login_events`: support (Phase 5) and the SQL agent
(Phase 6) already read that table to explain login problems, so real logins show up there too.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import limits
from app.accounts.google import GoogleAccount
from app.accounts.passwords import DUMMY_HASH, hash_password, password_problem, verify_password
from app.models import LoginEvent, Role, User, UserCredential

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(Exception):
    """A problem the person can fix (shown to them as is)."""

    def __init__(self, message: str, status: int = 400, retry_after: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retry_after = retry_after


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


async def credential_for(session: AsyncSession, user_id: int) -> UserCredential:
    cred = await session.get(UserCredential, user_id)
    if cred is None:
        cred = UserCredential(user_id=user_id, created_at=datetime.now(UTC))
        session.add(cred)
    return cred


async def create_user(
    session: AsyncSession,
    *,
    full_name: str,
    email: str,
    password: str | None = None,
    role: Role = Role.student,
    google_sub: str | None = None,
) -> User:
    email = normalize_email(email)
    full_name = " ".join(full_name.split())[:120]
    if not EMAIL_RE.match(email) or len(email) > 200:
        raise AccountError("Enter a valid email address.")
    if len(full_name) < 2:
        raise AccountError("Enter your full name.")
    if password is not None and (problem := password_problem(password, email)):
        raise AccountError(problem)
    if await user_by_email(session, email):
        raise AccountError("An account with this email already exists. Log in instead.", status=409)

    now = datetime.now(UTC)
    user = User(full_name=full_name, email=email, role=role, city="", joined_at=now, is_active=True)
    session.add(user)
    await session.flush()
    session.add(
        UserCredential(
            user_id=user.id,
            password_hash=hash_password(password) if password else None,
            google_sub=google_sub,
            password_changed_at=now if password else None,
            created_at=now,
        )
    )
    await session.flush()
    return user


async def record_login(session: AsyncSession, user: User, success: bool, reason: str | None = None) -> None:
    now = datetime.now(UTC)
    session.add(LoginEvent(user_id=user.id, occurred_at=now, success=success, failure_reason=reason, device="web"))
    if success:
        (await credential_for(session, user.id)).last_login_at = now


async def login_with_password(session: AsyncSession, email: str, password: str, ip: str | None) -> User:
    email = normalize_email(email)
    wait = limits.retry_after(email, ip)
    user = await user_by_email(session, email)
    if wait:
        if user:
            await record_login(session, user, False, "account_locked")
            await session.commit()
        minutes = max(1, round(wait / 60))
        raise AccountError(
            f"Too many wrong passwords. Try again in {minutes} minute{'s' if minutes > 1 else ''}, "
            "or sign in with Google.",
            status=429,
            retry_after=wait,
        )

    cred = await session.get(UserCredential, user.id) if user else None
    stored = cred.password_hash if cred else None
    ok = verify_password(password, stored or DUMMY_HASH) and stored is not None
    if not ok or user is None or not user.is_active:
        limits.record_failure(email, ip)
        if user:
            await record_login(session, user, False, "wrong_password" if user.is_active else "account_disabled")
            await session.commit()
        # One message for every case, so the form doesn't reveal which emails have accounts.
        raise AccountError(
            "Email or password is incorrect. If you signed up with Google, use the Google button.", status=401
        )

    limits.clear(email)
    await record_login(session, user, True)
    return user


async def login_with_google(session: AsyncSession, account: GoogleAccount, allow_signup: bool) -> tuple[User, bool]:
    """The user for a verified Google account: linked by Google id, else by (Google-verified) email, else new.

    Returns (user, created)."""
    cred = await session.scalar(select(UserCredential).where(UserCredential.google_sub == account.sub))
    user = await session.get(User, cred.user_id) if cred else None
    created = False
    if user is None:
        user = await user_by_email(session, account.email)
        if user is not None:
            # Google verified the email, so this person owns the account: link it.
            (await credential_for(session, user.id)).google_sub = account.sub
        elif allow_signup:
            user = await create_user(session, full_name=account.name, email=account.email, google_sub=account.sub)
            created = True
        else:
            raise AccountError("No account uses this Google email, and sign-up is closed. Ask an admin.", status=403)
    if not user.is_active:
        await record_login(session, user, False, "account_disabled")
        await session.commit()
        raise AccountError("This account is deactivated. Contact an admin.", status=403)
    await record_login(session, user, True)
    return user, created


async def change_password(session: AsyncSession, user: User, current: str | None, new: str) -> None:
    cred = await credential_for(session, user.id)
    if cred.password_hash and not verify_password(current or "", cred.password_hash):
        raise AccountError("Your current password is incorrect.", status=401)
    if problem := password_problem(new, user.email):
        raise AccountError(problem)
    cred.password_hash = hash_password(new)
    cred.password_changed_at = datetime.now(UTC)
