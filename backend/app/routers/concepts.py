"""Teacher (own courses) and admin (all courses): the concept graph of a course (Phase 3)."""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import SessionDep, require_roles
from app.graph import store as graph
from app.models import Course, Role, User
from app.permissions import PermissionDenied
from app.scopes import manageable_course_ids

router = APIRouter(prefix="/concepts", tags=["concepts"])
Manager = Depends(require_roles(Role.teacher, Role.admin))


@router.get("/courses/{course_id}")
async def course_graph(course_id: int, session: SessionDep, user: User = Manager):
    """Every concept of the course (draft, approved, rejected) and the prerequisite edges."""
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "Course not found.")
    if course_id not in await manageable_course_ids(session, user):
        raise PermissionDenied("You can only see the concept graph of your own courses.")
    course_out = {"id": course.id, "code": course.code, "title": course.title}
    return {"course": course_out, **await graph.course_graph(course_id)}
