"""Quizzes (Phase 3c).

Teachers and admins (courses they manage): generate a draft quiz from a file or topic (T10),
review every question with its source passage, then publish (T11).
Students (enrolled courses): take published quizzes (S15). Answers are graded here, and the
right answers only leave the server after submitting.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth import SessionDep, require_roles
from app.models import Course, Document, DocumentStatus, Module, Quiz, QuizAttempt, QuizQuestion, Role, Topic, User
from app.permissions import PermissionDenied
from app.quiz.generate import QuizError, generate_quiz, grade, tidy
from app.scopes import manageable_course_ids, readable_course_ids

router = APIRouter(prefix="/quizzes", tags=["quizzes"])
Manager = Depends(require_roles(Role.teacher, Role.admin))
Student = Depends(require_roles(Role.student))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _managed_course(session, user: User, course_id: int) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "Course not found.")
    if course_id not in await manageable_course_ids(session, user):
        raise PermissionDenied("You can only make quizzes for your own courses.")
    return course


async def _managed_quiz(session, user: User, quiz_id: int) -> Quiz:
    quiz = await session.get(Quiz, quiz_id)
    if quiz is None or quiz.created_by is None:  # seeded quizzes have no questions to manage
        raise HTTPException(404, "Quiz not found.")
    if quiz.course_id not in await manageable_course_ids(session, user):
        raise PermissionDenied("You can only manage quizzes of your own courses.")
    return quiz


async def _questions(session, quiz_id: int, statuses: tuple[str, ...] | None = None) -> list[QuizQuestion]:
    query = select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.position)
    if statuses:
        query = query.where(QuizQuestion.status.in_(statuses))
    return list((await session.scalars(query)).all())


def _source_out(q: QuizQuestion) -> dict:
    s = q.source or {}
    return {k: s.get(k) for k in ("document_id", "file_name", "page", "section", "text", "quote")}


def _question_out(q: QuizQuestion, with_answer: bool) -> dict:
    out = {"id": q.id, "position": q.position, "question": q.question, "options": q.options, "difficulty": q.difficulty}
    if with_answer:
        out |= {
            "correct_index": q.correct_index,
            "explanation": q.explanation,
            "status": q.status,
            "edited": q.edited,
            "source": _source_out(q),
        }
    return out


def _quiz_out(quiz: Quiz, course: Course | None = None, **extra) -> dict:
    return {
        "id": quiz.id,
        "title": quiz.title,
        "status": quiz.status,
        "course_id": quiz.course_id,
        "course_code": course.code if course else None,
        "source_label": quiz.source_label,
        "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
        "published_at": quiz.published_at.isoformat() if quiz.published_at else None,
        "generation_cost_usd": quiz.generation_cost_usd,
        **extra,
    }


async def _counts(session, quiz_ids: list[int]) -> dict[int, dict[str, int]]:
    rows = (
        await session.execute(
            select(QuizQuestion.quiz_id, QuizQuestion.status, func.count())
            .where(QuizQuestion.quiz_id.in_(quiz_ids or [-1]))
            .group_by(QuizQuestion.quiz_id, QuizQuestion.status)
        )
    ).all()
    out: dict[int, dict[str, int]] = {}
    for quiz_id, status, n in rows:
        out.setdefault(quiz_id, {"draft": 0, "approved": 0, "rejected": 0})[status] = n
    return out


# ---------------------------------------------------------------------------
# Teacher: generate, review, publish
# ---------------------------------------------------------------------------


@router.get("/manage")
async def list_managed(course_id: int, session: SessionDep, user: User = Manager):
    course = await _managed_course(session, user, course_id)
    quizzes = (
        await session.scalars(
            select(Quiz).where(Quiz.course_id == course_id, Quiz.created_by.is_not(None)).order_by(Quiz.id.desc())
        )
    ).all()
    counts = await _counts(session, [q.id for q in quizzes])
    attempts = dict(
        (
            await session.execute(
                select(QuizAttempt.quiz_id, func.count())
                .where(QuizAttempt.quiz_id.in_([q.id for q in quizzes] or [-1]))
                .group_by(QuizAttempt.quiz_id)
            )
        ).all()
    )
    return [_quiz_out(q, course, questions=counts.get(q.id, {}), attempts=attempts.get(q.id, 0)) for q in quizzes]


@router.get("/sources")
async def sources(course_id: int, session: SessionDep, user: User = Manager):
    """What a quiz can be generated from: the course's ready files and its topics (with indexed text)."""
    await _managed_course(session, user, course_id)
    files = (
        await session.execute(
            select(Document.id, Document.file_name, Module.title)
            .join(Module, Module.id == Document.module_id)
            .where(
                Document.course_id == course_id,
                Document.status == DocumentStatus.ready,
                Document.superseded_at.is_(None),
            )
            .order_by(Module.position, Document.file_name)
        )
    ).all()
    topics = (
        await session.execute(
            select(Topic.id, Topic.name, Module.title)
            .join(Module, Module.id == Topic.module_id)
            .where(Module.course_id == course_id)
            .order_by(Module.position, Topic.position)
        )
    ).all()
    return {
        "files": [{"id": i, "file_name": f, "module_title": m} for i, f, m in files],
        "topics": [{"id": i, "name": n, "module_title": m} for i, n, m in topics],
    }


class GenerateIn(BaseModel):
    course_id: int
    document_id: int | None = None
    topic_id: int | None = None
    num_questions: int = Field(5, ge=1, le=20)
    title: str | None = Field(None, max_length=160)


@router.post("/generate", status_code=201)
async def generate(body: GenerateIn, session: SessionDep, user: User = Manager):
    if (body.document_id is None) == (body.topic_id is None):
        raise HTTPException(422, "Pick either a file or a topic.")
    course = await _managed_course(session, user, body.course_id)
    document = topic = None
    if body.document_id is not None:
        document = await session.get(Document, body.document_id)
        if document is None or document.course_id != course.id:
            raise HTTPException(404, "File not found in this course.")
    else:
        topic = await session.get(Topic, body.topic_id)
        module = await session.get(Module, topic.module_id) if topic else None
        if module is None or module.course_id != course.id:
            raise HTTPException(404, "Topic not found in this course.")
    try:
        quiz, dropped = await generate_quiz(
            session,
            course=course,
            user=user,
            document=document,
            topic=topic,
            num_questions=body.num_questions,
            title=body.title,
        )
    except QuizError as exc:
        raise HTTPException(422, exc.message) from exc
    return {"quiz": _quiz_out(quiz, course), "dropped": dropped}


@router.get("/{quiz_id}/manage")
async def get_managed(quiz_id: int, session: SessionDep, user: User = Manager):
    quiz = await _managed_quiz(session, user, quiz_id)
    course = await session.get(Course, quiz.course_id)
    questions = await _questions(session, quiz.id)
    return {"quiz": _quiz_out(quiz, course), "questions": [_question_out(q, True) for q in questions]}


class QuizPatch(BaseModel):
    title: str | None = Field(None, max_length=160)
    status: Literal["draft", "published"] | None = None


@router.patch("/{quiz_id}")
async def update_quiz(quiz_id: int, body: QuizPatch, session: SessionDep, user: User = Manager):
    quiz = await _managed_quiz(session, user, quiz_id)
    if body.title is not None:
        if not (title := tidy(body.title, 160)):
            raise HTTPException(422, "The title is empty.")
        quiz.title = title
    if body.status == "published" and quiz.status != "published":
        counts = (await _counts(session, [quiz.id])).get(quiz.id, {})
        # Human approval is the point: every question is looked at before students see any.
        if counts.get("draft"):
            raise HTTPException(409, f"Review the {counts['draft']} remaining draft question(s) first.")
        if not counts.get("approved"):
            raise HTTPException(409, "Approve at least one question before publishing.")
        quiz.status, quiz.published_at = "published", datetime.now(UTC)
    elif body.status == "draft":
        quiz.status = "draft"  # unpublish: students no longer see it; past attempts stay
    await session.commit()
    return _quiz_out(quiz)


@router.delete("/{quiz_id}", status_code=204)
async def delete_quiz(quiz_id: int, session: SessionDep, user: User = Manager):
    quiz = await _managed_quiz(session, user, quiz_id)
    if await session.scalar(select(func.count()).where(QuizAttempt.quiz_id == quiz.id)):
        raise HTTPException(409, "Students have taken this quiz. Unpublish it instead, so their scores stay.")
    await session.delete(quiz)  # questions go with it (ON DELETE CASCADE)
    await session.commit()


class QuestionPatch(BaseModel):
    question: str | None = Field(None, max_length=600)
    options: list[str] | None = Field(None, min_length=4, max_length=4)
    correct_index: int | None = Field(None, ge=0, le=3)
    explanation: str | None = Field(None, max_length=800)
    status: Literal["draft", "approved", "rejected"] | None = None


@router.patch("/questions/{question_id}")
async def update_question(question_id: int, body: QuestionPatch, session: SessionDep, user: User = Manager):
    q = await session.get(QuizQuestion, question_id)
    if q is None:
        raise HTTPException(404, "Question not found.")
    quiz = await _managed_quiz(session, user, q.quiz_id)
    if body.question is not None:
        if not (text := tidy(body.question, 600)):
            raise HTTPException(422, "The question is empty.")
        q.question, q.edited = text, True
    if body.options is not None:
        options = [tidy(o, 300) for o in body.options]
        if any(not o for o in options) or len({o.lower() for o in options}) != 4:
            raise HTTPException(422, "Give 4 different, non-empty options.")
        q.options, q.edited = options, True
    if body.correct_index is not None:
        q.correct_index, q.edited = body.correct_index, True
    if body.explanation is not None:
        q.explanation, q.edited = tidy(body.explanation, 800), True
    if body.status is not None:
        q.status = body.status
    if quiz.status == "published" and not await _questions(session, quiz.id, ("approved",)):
        raise HTTPException(409, "A published quiz needs at least one approved question. Unpublish it first.")
    await session.commit()
    return _question_out(q, True)


# ---------------------------------------------------------------------------
# Students: take published quizzes
# ---------------------------------------------------------------------------


async def _published_quiz(session, user: User, quiz_id: int) -> Quiz:
    quiz = await session.get(Quiz, quiz_id)
    if (
        quiz is None
        or quiz.status != "published"
        or quiz.created_by is None
        or quiz.course_id not in await readable_course_ids(session, user)
    ):
        # Same answer for "doesn't exist", "draft" and "not your course".
        raise HTTPException(404, "Quiz not found.")
    return quiz


@router.get("")
async def list_for_student(session: SessionDep, user: User = Student):
    course_ids = await readable_course_ids(session, user)
    quizzes = (
        await session.scalars(
            select(Quiz)
            .where(Quiz.course_id.in_(course_ids), Quiz.status == "published", Quiz.created_by.is_not(None))
            .order_by(Quiz.published_at.desc())
        )
    ).all()
    counts = await _counts(session, [q.id for q in quizzes])
    courses = {c.id: c for c in (await session.scalars(select(Course).where(Course.id.in_(course_ids)))).all()}
    mine = (
        await session.execute(
            select(QuizAttempt.quiz_id, func.count(), func.max(QuizAttempt.score_pct))
            .where(QuizAttempt.student_id == user.id, QuizAttempt.quiz_id.in_([q.id for q in quizzes] or [-1]))
            .group_by(QuizAttempt.quiz_id)
        )
    ).all()
    tried = {quiz_id: (n, best) for quiz_id, n, best in mine}
    return [
        _quiz_out(
            q,
            courses.get(q.course_id),
            num_questions=counts[q.id]["approved"],
            attempts=tried.get(q.id, (0, None))[0],
            best_score=tried.get(q.id, (0, None))[1],
        )
        for q in quizzes
        if counts.get(q.id, {}).get("approved")
    ]


@router.get("/{quiz_id}")
async def take(quiz_id: int, session: SessionDep, user: User = Student):
    quiz = await _published_quiz(session, user, quiz_id)
    questions = await _questions(session, quiz.id, ("approved",))
    if not questions:
        raise HTTPException(404, "Quiz not found.")
    course = await session.get(Course, quiz.course_id)
    return {"quiz": _quiz_out(quiz, course), "questions": [_question_out(q, False) for q in questions]}


class AttemptIn(BaseModel):
    answers: dict[int, int | None]  # question id -> chosen option index (null = skipped)
    time_taken_sec: int = Field(0, ge=0)


@router.post("/{quiz_id}/attempts", status_code=201)
async def submit(quiz_id: int, body: AttemptIn, session: SessionDep, user: User = Student):
    quiz = await _published_quiz(session, user, quiz_id)
    questions = await _questions(session, quiz.id, ("approved",))
    if not questions:
        raise HTTPException(404, "Quiz not found.")
    score, results = grade(questions, body.answers)
    session.add(
        QuizAttempt(
            quiz_id=quiz.id,
            student_id=user.id,
            attempted_at=datetime.now(UTC),
            score_pct=score,
            time_taken_sec=min(body.time_taken_sec, 24 * 3600),
            answers=results,
        )
    )
    await session.commit()
    by_id = {q.id: q for q in questions}
    return {
        "score_pct": score,
        "results": [
            {
                **r,
                "correct_index": by_id[r["question_id"]].correct_index,
                "explanation": by_id[r["question_id"]].explanation,
                "source": _source_out(by_id[r["question_id"]]),
            }
            for r in results
        ],
    }
