"""Who is calling: the signed-in user behind the session cookie.

The cookie holds a random session id (app/accounts/sessions.py); a missing, expired or revoked
session, or a deactivated user, is a 401. Everything that needs "who is calling" depends on
`get_current_user`, and `require_roles` guards whole routes by role. What each role may then SEE is
decided by the permission matrix (app/permissions.py), not here.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import sessions
from app.config import get_settings
from app.db import get_session
from app.models import Role, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def session_token(request: Request) -> str | None:
    return request.cookies.get(get_settings().auth_cookie_name)


async def get_current_user(request: Request, session: SessionDep) -> User:
    user = await sessions.user_for(session, session_token(request))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "You are not logged in, or your session has ended.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    """Route guard: `Depends(require_roles(Role.admin))`."""

    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            allowed = ", ".join(r.value for r in roles)
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This page is only for: {allowed}.")
        return user

    return checker
