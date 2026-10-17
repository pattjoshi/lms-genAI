"""Admins manage accounts: list and search users, create staff accounts, change roles, deactivate.

Self-sign-up only ever creates students; this is the only way to make someone a teacher, support
agent or admin (besides the `python -m app.accounts` command used for the very first admin).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.accounts import sessions
from app.accounts.passwords import MAX_LENGTH
from app.accounts.service import AccountError, create_user
from app.auth import SessionDep, require_roles
from app.models import Role, User, UserCredential

router = APIRouter(prefix="/admin/users", tags=["users"])
Admin = Depends(require_roles(Role.admin))
PAGE_SIZE = 25


def _row(user: User, cred: UserCredential | None) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.value,
        "city": user.city,
        "is_active": user.is_active,
        "joined_at": user.joined_at.isoformat(),
        "has_password": bool(cred and cred.password_hash),
        "google_linked": bool(cred and cred.google_sub),
        "last_login_at": cred.last_login_at.isoformat() if cred and cred.last_login_at else None,
    }


@router.get("")
async def list_users(
    session: SessionDep,
    q: str = "",
    role: Role | None = None,
    page: int = 1,
    _: User = Admin,
):
    query = select(User, UserCredential).outerjoin(UserCredential, UserCredential.user_id == User.id)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    if role is not None:
        query = query.where(User.role == role)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    page = max(1, page)
    rows = (
        await session.execute(query.order_by(User.role, User.full_name).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE))
    ).all()
    counts = dict((await session.execute(select(User.role, func.count()).group_by(User.role))).all())
    return {
        "users": [_row(u, c) for u, c in rows],
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "by_role": {r.value: counts.get(r, 0) for r in Role},
    }


class NewUser(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=200)
    role: Role
    password: str = Field(max_length=MAX_LENGTH, description="A first password; ask them to change it")


@router.post("", status_code=201)
async def add_user(body: NewUser, session: SessionDep, _: User = Admin):
    try:
        user = await create_user(
            session, full_name=body.full_name, email=body.email, password=body.password, role=body.role
        )
    except AccountError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    await session.commit()
    return _row(user, await session.get(UserCredential, user.id))


class UserChange(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


@router.patch("/{user_id}")
async def change_user(user_id: int, body: UserChange, session: SessionDep, admin: User = Admin):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user.")
    if user.id == admin.id and (body.role not in (None, Role.admin) or body.is_active is False):
        # Otherwise the last admin could lock everyone out of user management.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't remove your own admin role or deactivate yourself.")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            await sessions.end_all(session, user.id)
    await session.commit()
    return _row(user, await session.get(UserCredential, user.id))
