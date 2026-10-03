"""Scoped data access: turns the permission matrix into SQL filters.

Layer 3 of the permission design ("the database only returns what you may see").
In Phase 0 it's done with WHERE clauses in Python; in Phase 6 the same rules move into
Postgres row-level security so even LLM-written SQL can't escape them.
"""

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Enrollment, EnrollmentStatus, Role, User
from app.permissions import PermissionDenied, Resource, Scope, scope_for


def student_list_query(user: User) -> Select[tuple[User]]:
    """Students the caller may LIST. Raises PermissionDenied if they may not list students."""
    scope = scope_for(user.role, Resource.STUDENT_RECORDS)
    base = select(User).where(User.role == Role.student).order_by(User.full_name)

    if scope == Scope.ALL:
        return base
    if scope == Scope.OWN_COURSES:
        my_course_ids = select(Course.id).where(Course.teacher_id == user.id)
        my_student_ids = select(Enrollment.student_id).where(Enrollment.course_id.in_(my_course_ids))
        return base.where(User.id.in_(my_student_ids))
    if scope == Scope.OWN:
        raise PermissionDenied("Students can't list other students. You can only see your own profile and scores.")
    if scope == Scope.TICKET_STUDENT:
        raise PermissionDenied(
            "Support staff can only see the student attached to a ticket (tickets arrive in Phase 5)."
        )
    raise PermissionDenied("You don't have access to student records.")


async def _course_ids_for_scope(session: AsyncSession, user: User, scope: Scope) -> list[int]:
    if scope == Scope.ALL:
        return list((await session.scalars(select(Course.id))).all())
    if scope == Scope.OWN_COURSES:
        return list((await session.scalars(select(Course.id).where(Course.teacher_id == user.id))).all())
    if scope == Scope.ENROLLED:
        # Dropped enrollments lose access to the material; active and completed keep it.
        query = select(Enrollment.course_id).where(
            Enrollment.student_id == user.id, Enrollment.status != EnrollmentStatus.dropped
        )
        return list((await session.scalars(query)).all())
    return []


async def readable_course_ids(session: AsyncSession, user: User) -> list[int]:
    """Courses whose material the user may read (used as a MANDATORY RAG retrieval filter)."""
    return await _course_ids_for_scope(session, user, scope_for(user.role, Resource.COURSE_MATERIAL))


async def manageable_course_ids(session: AsyncSession, user: User) -> list[int]:
    """Courses the user may upload to / delete files from."""
    return await _course_ids_for_scope(session, user, scope_for(user.role, Resource.MANAGE_MATERIAL))
