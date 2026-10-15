"""Tickets, the knowledge base and teacher insights (Phase 5).

Students        GET  /tickets/mine            S19: my tickets and their answers
                POST /tickets                 ask support directly
                POST /chat/doubts/{id}/feedback   (in chat.py) S6: 👍/👎, 👎 opens a ticket
Support, admin  GET  /tickets                 P1: the queue, with filters
                GET  /tickets/{id}            P3: full context, similar tickets (P7), the student (P8)
                POST /tickets/{id}/claim      take it (in progress)
                POST /tickets/{id}/course     set the course (needed for the knowledge base)
                POST /tickets/{id}/resolve    P4-P6: answer, and save to the knowledge base or not
                GET  /kb, DELETE /kb/{id}     P5: knowledge-base entries; withdraw one
Teacher, admin  GET  /insights                T13, T14: most asked doubts, content gaps
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import CurrentUser, SessionDep, require_roles
from app.models import FaqEntry, Role, User
from app.tickets import insights as insights_svc
from app.tickets import service as svc

router = APIRouter(tags=["tickets"])

Staff = Depends(require_roles(Role.support, Role.admin))


class NewTicket(BaseModel):
    subject: str = Field(min_length=5, max_length=500)
    details: str = Field("", max_length=4000)


class Resolve(BaseModel):
    resolution: str = Field(min_length=1, max_length=8000)
    save_to_kb: bool = False


class SetCourse(BaseModel):
    course_id: int | None = None


def _raise(exc: svc.TicketError):
    raise HTTPException(exc.status, exc.message)


@router.get("/tickets/mine")
async def my_tickets(session: SessionDep, user: CurrentUser):
    return await svc.mine(session, user)


@router.post("/tickets", status_code=201)
async def new_ticket(body: NewTicket, session: SessionDep, user: User = Depends(require_roles(Role.student))):
    ticket = await svc.open_by_student(session, user, body.subject, body.details)
    await session.commit()
    return svc.row(ticket)


@router.get("/tickets")
async def ticket_queue(
    session: SessionDep,
    status: str | None = None,
    reason: str | None = None,
    category: str | None = None,
    course_id: int | None = None,
    user: User = Staff,
):
    return await svc.queue(session, status=status, reason=reason, category=category, course_id=course_id)


@router.get("/tickets/{ticket_id}")
async def ticket_detail(ticket_id: int, session: SessionDep, user: User = Staff):
    try:
        out = await svc.detail(session, user, ticket_id)
    except svc.TicketError as exc:
        _raise(exc)
    await session.commit()  # keeps the vector embedded for "similar tickets"
    return out


@router.post("/tickets/{ticket_id}/claim")
async def claim(ticket_id: int, session: SessionDep, user: User = Staff):
    try:
        ticket = await svc.claim(session, user, ticket_id)
    except svc.TicketError as exc:
        _raise(exc)
    await session.commit()
    return svc.row(ticket, assignee=user.full_name)


@router.post("/tickets/{ticket_id}/course")
async def set_course(ticket_id: int, body: SetCourse, session: SessionDep, user: User = Staff):
    try:
        ticket = await svc.set_course(session, ticket_id, body.course_id)
    except svc.TicketError as exc:
        _raise(exc)
    await session.commit()
    return svc.row(ticket)


@router.post("/tickets/{ticket_id}/resolve")
async def resolve(ticket_id: int, body: Resolve, session: SessionDep, user: User = Staff):
    try:
        ticket = await svc.resolve(session, user, ticket_id, body.resolution, body.save_to_kb)
    except svc.TicketError as exc:
        _raise(exc)
    await session.commit()
    return svc.row(ticket)


@router.get("/kb")
async def kb(session: SessionDep, include_inactive: bool = False, user: User = Staff):
    return await svc.faq_list(session, include_inactive)


@router.delete("/kb/{entry_id}", status_code=204)
async def withdraw(entry_id: int, session: SessionDep, user: User = Staff):
    entry = await session.get(FaqEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Knowledge-base entry not found.")
    entry.active = False  # kept for the record; retrieval stops using it
    await session.commit()


@router.get("/insights")
async def insights(
    session: SessionDep,
    days: int | None = None,
    course_code: str | None = None,
    user: User = Depends(require_roles(Role.teacher, Role.admin)),
):
    return await insights_svc.insights(session, user, days=min(days, 365) if days else None, course_code=course_code)
