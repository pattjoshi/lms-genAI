"""Practice questions created in the chat (Phase 4, S13 + S14). Answering happens here, one question at a time."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent import practice as svc
from app.auth import CurrentUser, SessionDep
from app.models import Course, PracticeSet

router = APIRouter(prefix="/practice", tags=["practice"])


@router.get("/{practice_id}")
async def get_practice(practice_id: int, session: SessionDep, user: CurrentUser):
    practice = await session.get(PracticeSet, practice_id)
    if practice is None or practice.student_id != user.id:
        raise HTTPException(404, "Practice not found.")
    course = await session.get(Course, practice.course_id)
    return svc.public(practice, course.code if course else None)


class AnswerIn(BaseModel):
    index: int = Field(ge=0)
    chosen: int = Field(ge=0, le=3)


@router.post("/{practice_id}/answers")
async def answer(practice_id: int, body: AnswerIn, session: SessionDep, user: CurrentUser):
    try:
        return await svc.answer(session, user, practice_id, body.index, body.chosen)
    except svc.PracticeError as exc:
        raise HTTPException(404, exc.message) from exc
