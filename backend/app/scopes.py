"""Scoped data access: turns the permission matrix into SQL filters.

Layer 3 of the permission design ("the database only returns what you may see").
In Phase 0 it's done with WHERE clauses in Python; in Phase 6 the same rules move into
Postgres row-level security so even LLM-written SQL can't escape them.
"""

from sqlalchemy import Select, select

from app.models import Course, Enrollment, Role, User
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
