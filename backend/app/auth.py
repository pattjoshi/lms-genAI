"""Dummy login.

There are no passwords or tokens on purpose (this project is about GenAI, not auth).
The frontend sends the chosen user's id in the `X-User-Id` header and we trust it.

Everything that needs "who is calling" depends on `get_current_user`, so switching
to real JWT auth later means changing only this file.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Role, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    x_user_id: Annotated[int | None, Header()] = None,
) -> User:
    if x_user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in. Pick a user on the login page.")
    user = await session.get(User, x_user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or inactive user. Log in again.")
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
