"""Teacher (own courses) and admin (all courses): review the concept graph of a course (Phase 3).

Every action checks that the concept belongs to a course the user manages. The uid comes
from the browser, so it is never trusted on its own.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import SessionDep, require_roles
from app.graph import review
from app.graph import store as graph
from app.models import Course, Role, User
from app.permissions import PermissionDenied
from app.scopes import manageable_course_ids

router = APIRouter(prefix="/concepts", tags=["concepts"])
Manager = Depends(require_roles(Role.teacher, Role.admin))


async def _check_course(session, user: User, course_id: int | None) -> int:
    if course_id is None:
        raise HTTPException(404, "Concept not found.")
    if course_id not in await manageable_course_ids(session, user):
        raise PermissionDenied("You can only review the concepts of your own courses.")
    return course_id


async def _check_concept(session, user: User, uid: str) -> int:
    return await _check_course(session, user, await review.concept_course(uid))


async def _run(action):
    try:
        return await action
    except review.ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.get("/courses/{course_id}")
async def course_graph(course_id: int, session: SessionDep, user: User = Manager):
    """Every concept of the course (draft, approved, rejected) and the prerequisite edges."""
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "Course not found.")
    await _check_course(session, user, course_id)
    course_out = {"id": course.id, "code": course.code, "title": course.title}
    return {"course": course_out, **await graph.course_graph(course_id)}


@router.post("/courses/{course_id}/approve-drafts")
async def approve_drafts(course_id: int, session: SessionDep, user: User = Manager):
    await _check_course(session, user, course_id)
    return {"approved": await review.approve_drafts(course_id)}


class ConceptPatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    definition: str | None = Field(None, max_length=500)
    status: Literal["draft", "approved", "rejected"] | None = None


@router.patch("/{uid}")
async def update_concept(uid: str, body: ConceptPatch, session: SessionDep, user: User = Manager):
    await _check_concept(session, user, uid)
    await _run(review.update_concept(uid, name=body.name, definition=body.definition, status=body.status))
    return {"ok": True}


class MergeIn(BaseModel):
    into: str


@router.post("/{uid}/merge")
async def merge(uid: str, body: MergeIn, session: SessionDep, user: User = Manager):
    """This concept is the same as `into`: move its links and names there, then delete it."""
    await _check_concept(session, user, uid)
    await _check_concept(session, user, body.into)
    return await _run(review.merge_concepts(uid, body.into))


class PrerequisiteIn(BaseModel):
    prerequisite: str


@router.post("/{uid}/prerequisites")
async def add_prerequisite(uid: str, body: PrerequisiteIn, session: SessionDep, user: User = Manager):
    await _check_concept(session, user, uid)
    await _check_concept(session, user, body.prerequisite)
    await _run(review.add_prerequisite(uid, body.prerequisite))
    return {"ok": True}


class EdgePatch(BaseModel):
    prerequisite: str
    status: Literal["approved", "rejected"]


@router.patch("/{uid}/prerequisites")
async def set_prerequisite(uid: str, body: EdgePatch, session: SessionDep, user: User = Manager):
    await _check_concept(session, user, uid)
    await _check_concept(session, user, body.prerequisite)
    await _run(review.set_prerequisite_status(uid, body.prerequisite, body.status))
    return {"ok": True}
