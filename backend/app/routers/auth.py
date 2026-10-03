"""Dummy login endpoints: list the users to pick from, and "who am I"."""

from fastapi import APIRouter
from sqlalchemy import select

from app.auth import CurrentUser, SessionDep
from app.models import Role, User
from app.seed.catalog import STORY_USERS

router = APIRouter(prefix="/auth", tags=["auth"])
ROLE_ORDER = {Role.admin: 0, Role.teacher: 1, Role.support: 2, Role.student: 3}


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.value,
        "city": user.city,
        "story": STORY_USERS.get(user.email),  # why this user is interesting to log in as
    }


@router.get("/users")
async def list_login_users(session: SessionDep):
    """Everyone you can log in as. Users with a planted 'story' come first."""
    users = (await session.scalars(select(User).where(User.is_active).order_by(User.id))).all()
    out = [_user_out(u) for u in users]
    out.sort(key=lambda u: (ROLE_ORDER[u["role"]], u["story"] is None))  # stable: keeps id order inside a group
    return out


@router.get("/me")
async def me(user: CurrentUser):
    return _user_out(user)
