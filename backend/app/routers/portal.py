"""One summary endpoint per portal. Each is locked to its role (layer 2: route guards).

These are deliberately small: the portals are "empty shells" in Phase 0, with just
enough real data to prove the seed and the scoping work.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.auth import SessionDep, require_roles
from app.config import get_settings
from app.llm.budget import spent_today_usd, start_of_today
from app.models import (
    Course,
    Enrollment,
    EnrollmentStatus,
    LLMUsage,
    Module,
    Payment,
    PaymentStatus,
    Quiz,
    QuizAttempt,
    Role,
    Topic,
    User,
)

router = APIRouter(prefix="/portal", tags=["portal"])


@router.get("/student/summary")
async def student_summary(session: SessionDep, user: User = Depends(require_roles(Role.student))):
    enrollments = (
        await session.execute(
            select(Course.code, Course.title, Enrollment.status, Enrollment.progress_pct)
            .join(Course, Course.id == Enrollment.course_id)
            .where(Enrollment.student_id == user.id)
            .order_by(Course.code)
        )
    ).all()

    topic_avg = (
        select(Topic.name, Course.code, func.round(func.avg(QuizAttempt.score_pct)).label("avg_score"))
        .select_from(QuizAttempt)
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .join(Topic, Topic.id == Quiz.topic_id)
        .join(Module, Module.id == Topic.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(QuizAttempt.student_id == user.id)  # scope: OWN
        .group_by(Topic.name, Course.code)
    )
    weakest = (await session.execute(topic_avg.order_by("avg_score").limit(3))).all()

    return {
        "courses": [{"code": c, "title": t, "status": s.value, "progress_pct": p} for c, t, s, p in enrollments],
        "weakest_topics": [{"topic": t, "course": c, "avg_score": int(a)} for t, c, a in weakest],
    }


@router.get("/teacher/summary")
async def teacher_summary(session: SessionDep, user: User = Depends(require_roles(Role.teacher))):
    courses = (await session.scalars(select(Course).where(Course.teacher_id == user.id))).all()
    out = []
    for course in courses:
        counts = dict(
            (
                await session.execute(
                    select(Enrollment.status, func.count())
                    .where(Enrollment.course_id == course.id)
                    .group_by(Enrollment.status)
                )
            ).all()
        )
        hardest = (
            await session.execute(
                select(Topic.name, func.round(func.avg(QuizAttempt.score_pct)).label("avg_score"))
                .select_from(QuizAttempt)
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .join(Topic, Topic.id == Quiz.topic_id)
                .join(Module, Module.id == Topic.module_id)
                .where(Module.course_id == course.id)
                .group_by(Topic.name)
                .order_by("avg_score")
                .limit(3)
            )
        ).all()
        out.append(
            {
                "code": course.code,
                "title": course.title,
                "enrolled": sum(counts.values()),
                "active": counts.get(EnrollmentStatus.active, 0),
                "completed": counts.get(EnrollmentStatus.completed, 0),
                "dropped": counts.get(EnrollmentStatus.dropped, 0),
                "hardest_topics": [{"topic": t, "avg_score": int(a)} for t, a in hardest],
            }
        )
    return {"courses": out}


@router.get("/admin/summary")
async def admin_summary(session: SessionDep, user: User = Depends(require_roles(Role.admin))):
    settings = get_settings()
    since_30d = datetime.now(UTC) - timedelta(days=30)

    users_by_role = dict((await session.execute(select(User.role, func.count()).group_by(User.role))).all())
    revenue_30d = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount_inr), 0)).where(
            Payment.status == PaymentStatus.success, Payment.created_at >= since_30d
        )
    )
    failed_payments_30d = await session.scalar(
        select(func.count()).where(Payment.status == PaymentStatus.failed, Payment.created_at >= since_30d)
    )

    today = start_of_today(settings)
    calls_today, errors_today = (
        await session.execute(
            select(func.count(), func.count().filter(LLMUsage.status == "error")).where(LLMUsage.created_at >= today)
        )
    ).one()
    recent_calls = (await session.scalars(select(LLMUsage).order_by(LLMUsage.id.desc()).limit(10))).all()

    return {
        "users_by_role": {r.value: n for r, n in users_by_role.items()},
        "enrollments": await session.scalar(select(func.count()).select_from(Enrollment)),
        "revenue_inr_30d": int(revenue_30d or 0),
        "failed_payments_30d": failed_payments_30d,
        "ai_today": {
            "calls": calls_today,
            "errors": errors_today,
            "cost_usd": round(await spent_today_usd(session, settings), 6),
            "budget_usd": settings.daily_budget_usd,
        },
        "recent_ai_calls": [
            {
                "at": r.created_at.isoformat(),
                "feature": r.feature,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": r.cost_usd,
                "latency_ms": r.latency_ms,
                "attempts": r.attempts,
                "status": r.status,
                "error_code": r.error_code,
            }
            for r in recent_calls
        ],
    }


@router.get("/support/summary")
async def support_summary(user: User = Depends(require_roles(Role.support))):
    # Support only sees a student's data through a ticket, and tickets arrive in Phase 5.
    return {"tickets": [], "note": "The ticket queue arrives in Phase 5."}
