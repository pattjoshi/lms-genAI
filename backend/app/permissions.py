"""The permission matrix, as code.

This is the single source of truth for "who may see what". PLAN.md shows the same
table for humans. Every data access goes through `scope_for()`; later, the agent's
tool list and the SQL agent's database access are built from it too.

The LLM is NOT a security boundary: a prompt can be talked out of a rule, this table can't.
"""

from enum import StrEnum

from app.models import Role


class Resource(StrEnum):
    STUDENT_RECORDS = "student_records"  # profile, enrollments, quiz scores
    COURSE_MATERIAL = "course_material"  # read uploaded files / chunks (RAG answers)
    MANAGE_MATERIAL = "manage_material"  # upload / delete course files
    PAYMENTS = "payments"
    AI_USAGE = "ai_usage"  # token cost / latency dashboard


class Scope(StrEnum):
    NONE = "none"  # no access at all
    OWN = "own"  # only rows about the user themself
    ENROLLED = "enrolled"  # only courses the student is enrolled in
    OWN_COURSES = "own_courses"  # only courses the teacher owns (and their students)
    TICKET_STUDENT = "ticket_student"  # only the student attached to an open ticket (Phase 5)
    ALL = "all"


PERMISSIONS: dict[Role, dict[Resource, Scope]] = {
    Role.student: {
        Resource.STUDENT_RECORDS: Scope.OWN,
        Resource.COURSE_MATERIAL: Scope.ENROLLED,
        Resource.MANAGE_MATERIAL: Scope.NONE,
        Resource.PAYMENTS: Scope.OWN,
        Resource.AI_USAGE: Scope.NONE,
    },
    Role.teacher: {
        Resource.STUDENT_RECORDS: Scope.OWN_COURSES,
        Resource.COURSE_MATERIAL: Scope.OWN_COURSES,
        Resource.MANAGE_MATERIAL: Scope.OWN_COURSES,
        Resource.PAYMENTS: Scope.NONE,
        Resource.AI_USAGE: Scope.NONE,
    },
    Role.admin: {
        Resource.STUDENT_RECORDS: Scope.ALL,
        Resource.COURSE_MATERIAL: Scope.ALL,
        Resource.MANAGE_MATERIAL: Scope.ALL,
        Resource.PAYMENTS: Scope.ALL,
        Resource.AI_USAGE: Scope.ALL,
    },
    Role.support: {
        Resource.STUDENT_RECORDS: Scope.TICKET_STUDENT,
        Resource.COURSE_MATERIAL: Scope.ALL,
        Resource.MANAGE_MATERIAL: Scope.NONE,
        Resource.PAYMENTS: Scope.TICKET_STUDENT,
        Resource.AI_USAGE: Scope.NONE,
    },
}


class PermissionDenied(Exception):
    """Raised when a role asks for data outside its scope. Turned into HTTP 403."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def scope_for(role: Role, resource: Resource) -> Scope:
    # Unknown role/resource -> NONE. Deny by default.
    return PERMISSIONS.get(role, {}).get(resource, Scope.NONE)
