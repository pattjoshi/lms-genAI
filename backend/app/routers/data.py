"""Scoped data endpoints. Same URL, different answer per role.

GET /data/students
  student -> 403 (can't list other students)
  teacher -> only students enrolled in the teacher's own courses
  admin   -> all students
  support -> 403 until tickets exist (Phase 5)
"""

from fastapi import APIRouter
from sqlalchemy import func, select

from app.auth import CurrentUser, SessionDep
from app.permissions import Resource, scope_for
from app.scopes import student_list_query

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/students")
async def list_students(session: SessionDep, user: CurrentUser, limit: int = 50):
    query = student_list_query(user)  # raises PermissionDenied -> 403
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    students = (await session.scalars(query.limit(min(limit, 200)))).all()
    return {
        "scope": scope_for(user.role, Resource.STUDENT_RECORDS).value,
        "total": total,
        "students": [{"id": s.id, "full_name": s.full_name, "email": s.email, "city": s.city} for s in students],
    }
