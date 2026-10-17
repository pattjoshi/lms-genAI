"""What the public landing pages show without logging in: the course catalogue and a few totals.

Only catalogue data and counts: no names of students, no scores, no payments.
"""

from collections import Counter

from fastapi import APIRouter
from sqlalchemy import func, select

from app.auth import SessionDep
from app.models import Course, Doubt, Enrollment, EnrollmentStatus, Module, Role, Topic, User

router = APIRouter(prefix="/public", tags=["public"])

# Course code prefix -> category on the landing page. Unknown prefixes go under "More".
CATEGORIES = {
    "PY": "Programming",
    "DSA": "Computer science",
    "ML": "AI and machine learning",
    "DL": "AI and machine learning",
    "NLP": "AI and machine learning",
    "DB": "Data",
}
LEVELS = {"easy": "Beginner", "medium": "Intermediate", "hard": "Advanced"}


def category_for(code: str) -> str:
    prefix = code.rstrip("0123456789")
    return CATEGORIES.get(prefix, "More")


@router.get("/catalog")
async def catalog(session: SessionDep):
    courses = (
        await session.execute(
            select(Course, User.full_name).join(User, User.id == Course.teacher_id).order_by(Course.code)
        )
    ).all()
    learners = dict(
        (
            await session.execute(
                select(Enrollment.course_id, func.count())
                .where(Enrollment.status != EnrollmentStatus.dropped)
                .group_by(Enrollment.course_id)
            )
        ).all()
    )
    topics = (
        await session.execute(
            select(Module.course_id, Module.id, Topic.name, Topic.difficulty).join(Topic, Topic.module_id == Module.id)
        )
    ).all()
    by_course: dict[int, list] = {}
    for course_id, module_id, name, difficulty in topics:
        by_course.setdefault(course_id, []).append((module_id, name, difficulty.value))

    out = []
    for course, teacher in courses:
        rows = by_course.get(course.id, [])
        level = Counter(d for _, _, d in rows).most_common(1)
        out.append(
            {
                "code": course.code,
                "title": course.title,
                "description": course.description,
                "price_inr": course.price_inr,
                "teacher": teacher,
                "category": category_for(course.code),
                "level": LEVELS.get(level[0][0], "All levels") if level else "All levels",
                "modules": len({m for m, _, _ in rows}),
                "topics": [n for _, n, _ in rows][:6],
                "topic_count": len(rows),
                "learners": learners.get(course.id, 0),
            }
        )
    return {"courses": out, "categories": sorted({c["category"] for c in out})}


@router.get("/stats")
async def stats(session: SessionDep):
    return {
        "learners": await session.scalar(select(func.count()).where(User.role == Role.student, User.is_active)),
        "instructors": await session.scalar(select(func.count()).where(User.role == Role.teacher, User.is_active)),
        "courses": await session.scalar(select(func.count()).select_from(Course)),
        "questions_answered": await session.scalar(select(func.count()).where(Doubt.status == "answered")),
    }
