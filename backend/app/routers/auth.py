"""Sign up, log in (password or Google), log out, "who am I", and the dev-only demo login."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.accounts import sessions
from app.accounts.google import GoogleTokenError, verify_credential
from app.accounts.passwords import MAX_LENGTH, MIN_LENGTH
from app.accounts.service import (
    AccountError,
    change_password,
    create_user,
    login_with_google,
    login_with_password,
    record_login,
)
from app.auth import CurrentUser, SessionDep, session_token
from app.config import get_settings
from app.models import Role, User, UserCredential
from app.seed.catalog import STORY_USERS

router = APIRouter(prefix="/auth", tags=["auth"])
ROLE_ORDER = {Role.admin: 0, Role.teacher: 1, Role.support: 2, Role.student: 3}


def _user_out(user: User, cred: UserCredential | None = None) -> dict:
    out = {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.value,
        "city": user.city,
        "story": STORY_USERS.get(user.email),  # why this seeded user is interesting to log in as
    }
    if cred is not None:
        out["has_password"] = cred.password_hash is not None
        out["google_linked"] = cred.google_sub is not None
    return out


def _fail(exc: AccountError) -> HTTPException:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return HTTPException(exc.status, exc.message, headers=headers)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _signed_in(session: SessionDep, request: Request, response: Response, user: User, method: str) -> dict:
    token = await sessions.start(session, user, method, request.headers.get("user-agent"))
    await session.commit()
    sessions.set_cookie(response, token)
    return _user_out(user)


def _demo_enabled() -> bool:
    s = get_settings()
    return s.auth_demo_login and s.app_env == "dev"


@router.get("/config")
async def auth_config():
    """What the login page should offer."""
    s = get_settings()
    return {
        "google_client_id": s.google_client_id,
        "signup_open": s.auth_signup_open,
        "demo_login": _demo_enabled(),
        "password_min_length": MIN_LENGTH,
    }


class SignupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=200)
    password: str = Field(max_length=MAX_LENGTH)


@router.post("/signup", status_code=201)
async def signup(body: SignupIn, request: Request, response: Response, session: SessionDep):
    """Anyone can create a STUDENT account. Teacher, support and admin roles are given by an admin."""
    if not get_settings().auth_signup_open:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is closed. Ask an admin to create your account.")
    try:
        user = await create_user(session, full_name=body.full_name, email=body.email, password=body.password)
    except AccountError as exc:
        raise _fail(exc) from exc
    await record_login(session, user, True)
    return await _signed_in(session, request, response, user, "signup")


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=MAX_LENGTH)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep):
    try:
        user = await login_with_password(session, body.email, body.password, _client_ip(request))
    except AccountError as exc:
        raise _fail(exc) from exc
    return await _signed_in(session, request, response, user, "password")


class GoogleIn(BaseModel):
    credential: str = Field(max_length=4096)  # the ID token from Google's button


@router.post("/google")
async def google(body: GoogleIn, request: Request, response: Response, session: SessionDep):
    try:
        account = await verify_credential(body.credential)
        user, created = await login_with_google(session, account, allow_signup=get_settings().auth_signup_open)
    except GoogleTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except AccountError as exc:
        raise _fail(exc) from exc
    out = await _signed_in(session, request, response, user, "google")
    return {**out, "created": created}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, session: SessionDep):
    await sessions.end(session, session_token(request))
    await session.commit()
    sessions.clear_cookie(response)


@router.get("/me")
async def me(user: CurrentUser, session: SessionDep):
    return _user_out(user, await session.get(UserCredential, user.id))


class PasswordIn(BaseModel):
    current_password: str | None = Field(default=None, max_length=MAX_LENGTH)  # not needed when none is set yet
    new_password: str = Field(max_length=MAX_LENGTH)


@router.post("/password", status_code=204)
async def set_password(body: PasswordIn, request: Request, user: CurrentUser, session: SessionDep):
    """Change (or, for Google-only accounts, add) a password. Signs out every other browser."""
    try:
        await change_password(session, user, body.current_password, body.new_password)
    except AccountError as exc:
        raise _fail(exc) from exc
    await sessions.end_all(session, user.id, keep_token=session_token(request))
    await session.commit()


# --- Demo login (dev only): the seeded users have no passwords; pick one to explore a role ---


def _require_demo() -> None:
    if not _demo_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo login is off.")


@router.get("/users", dependencies=[Depends(_require_demo)])
async def list_demo_users(session: SessionDep):
    """Everyone you can log in as in demo mode. Users with a planted 'story' come first."""
    users = (await session.scalars(select(User).where(User.is_active).order_by(User.id))).all()
    out = [_user_out(u) for u in users]
    out.sort(key=lambda u: (ROLE_ORDER[Role(u["role"])], u["story"] is None))  # stable: keeps id order in a group
    return out


class DemoIn(BaseModel):
    user_id: int


@router.post("/demo-login", dependencies=[Depends(_require_demo)])
async def demo_login(body: DemoIn, request: Request, response: Response, session: SessionDep):
    user = await session.get(User, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown or inactive user.")
    await record_login(session, user, True)
    return await _signed_in(session, request, response, user, "demo")
