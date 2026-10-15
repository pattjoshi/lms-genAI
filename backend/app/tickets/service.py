"""Tickets (Phase 5): when a person has to look at a question.

A ticket is opened automatically from a chat message (P2) when
    - the AI found nothing in the course material              reason "no_answer"
    - it answered, but with low confidence                     reason "low_confidence"
    - the student pressed 👎                                    reason "thumbs_down"
    - it is a login or payment problem (no LLM answers these)   reason "support"
and by the student themself ("student", from My tickets or the MCP tool `create_ticket`).

Support sees the full context (P3): the question, the query that was actually searched, the passages the AI
read, its draft and confidence, and the student. They edit the draft and resolve (P4). A resolved COURSE
answer is saved to the knowledge base (P5, faq.py) unless support unticks it (P6), and retrieval uses it the
next time anyone asks the same thing. That is the feedback loop: a human fixes an answer once, the AI
reuses it.

P8, data scope: support sees a student's records (enrollments, payments, logins) only through a ticket, and
only while that ticket is open. Once it is resolved they see the conversation, not the records.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.support import is_login_problem
from app.config import get_settings
from app.llm.service import embed_texts
from app.models import (
    Chunk,
    Course,
    Doubt,
    Enrollment,
    FaqEntry,
    LoginEvent,
    Payment,
    Role,
    Ticket,
    User,
)
from app.permissions import Resource, Scope, scope_for
from app.tickets import vectors

log = logging.getLogger(__name__)

REASONS = ("no_answer", "low_confidence", "thumbs_down", "support", "student")
CATEGORIES = ("academic", "login", "payment")
STATUSES = ("open", "in_progress", "resolved")


class TicketError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


# ---------------------------------------------------------------------------
# Opening tickets
# ---------------------------------------------------------------------------


def auto_reason(doubt: Doubt) -> str | None:
    """Why a chat message needs a person, or None. Only course questions and support messages qualify:
    a learning path or practice set that found nothing tells the student what to do instead."""
    if doubt.intent == "support":
        return "support"
    if doubt.intent not in (None, "doubt"):
        return None
    if doubt.status == "no_context":
        return "no_answer" if get_settings().ticket_on_no_answer else None
    if doubt.status == "answered" and doubt.confidence == "low":
        return "low_confidence"
    return None


def category_for(text: str, intent: str | None) -> str:
    if intent != "support":
        return "academic"
    return "login" if is_login_problem(text) else "payment"


async def _course_from_sources(session: AsyncSession, sources: list | None) -> int | None:
    """Best guess at the course: the top retrieved passage's course (even an unused one points the right way)."""
    for s in sources or []:
        if s.get("course_code"):
            return await session.scalar(select(Course.id).where(Course.code == s["course_code"]))
    return None


async def open_for_doubt(
    session: AsyncSession, doubt: Doubt, reason: str, course_id: int | None = None
) -> tuple[Ticket, bool]:
    """Open (or find) the ticket for a chat message. One ticket per message: a 👎 on a message that already
    has a ticket marks that ticket instead of opening a second one. Returns (ticket, created)."""
    existing = await session.scalar(select(Ticket).where(Ticket.doubt_id == doubt.id))
    if existing is not None:
        if reason == "thumbs_down" and existing.reason != "thumbs_down":
            existing.reason = "thumbs_down"
            if existing.status == "resolved":  # the student still isn't happy: back in the queue
                existing.status, existing.resolved_at = "open", None
        return existing, False
    category = category_for(doubt.question, doubt.intent)
    ticket = Ticket(
        student_id=doubt.student_id,
        doubt_id=doubt.id,
        course_id=course_id or await _course_from_sources(session, doubt.sources),
        reason=reason,
        category=category,
        subject=doubt.question,
        # The AI's answer is the draft support starts from. "I couldn't find this" is not a useful draft.
        draft=doubt.answer if doubt.status == "answered" and category == "academic" else None,
        status="open",
    )
    session.add(ticket)
    await session.flush()
    return ticket, True


async def open_by_student(session: AsyncSession, student: User, subject: str, details: str = "") -> Ticket:
    text = subject.strip() + (f"\n\n{details.strip()}" if details.strip() else "")
    lowered = text.lower()
    category = (
        "login"
        if is_login_problem(text)
        else "payment"
        if any(w in lowered for w in ("payment", "refund", "paid", "charged", "upi", "card"))
        else "academic"
    )
    ticket = Ticket(student_id=student.id, reason="student", category=category, subject=text, status="open")
    session.add(ticket)
    await session.flush()
    return ticket


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def row(t: Ticket, student: str | None = None, course: str | None = None, assignee: str | None = None) -> dict:
    return {
        "id": t.id,
        "subject": t.subject,
        "reason": t.reason,
        "category": t.category,
        "status": t.status,
        "student": student,
        "course_code": course,
        "assigned_to": assignee,
        "doubt_id": t.doubt_id,
        "resolution": t.resolution,
        "saved_to_kb": t.saved_to_kb,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
    }


async def mine(session: AsyncSession, user: User) -> list[dict]:
    """S19: the student's own tickets (scope: OWN)."""
    rows = (
        await session.execute(
            select(Ticket, Course.code)
            .outerjoin(Course, Course.id == Ticket.course_id)
            .where(Ticket.student_id == user.id)
            .order_by(Ticket.id.desc())
            .limit(50)
        )
    ).all()
    return [row(t, course=code) for t, code in rows]


async def queue(
    session: AsyncSession,
    *,
    status: str | None = None,
    reason: str | None = None,
    category: str | None = None,
    course_id: int | None = None,
    limit: int = 100,
) -> dict:
    """P1: the queue, oldest open first (first come, first served), with counts for the filter chips."""
    Student, Assignee = User.__table__.alias("student"), User.__table__.alias("assignee")
    query = (
        select(Ticket, Student.c.full_name, Course.code, Assignee.c.full_name)
        .join(Student, Student.c.id == Ticket.student_id)
        .outerjoin(Course, Course.id == Ticket.course_id)
        .outerjoin(Assignee, Assignee.c.id == Ticket.assigned_to)
    )
    if status:
        query = query.where(Ticket.status == status)
    if reason:
        query = query.where(Ticket.reason == reason)
    if category:
        query = query.where(Ticket.category == category)
    if course_id:
        query = query.where(Ticket.course_id == course_id)
    order = Ticket.id.desc() if status == "resolved" else Ticket.id
    rows = (await session.execute(query.order_by(order).limit(min(limit, 200)))).all()
    counts = dict((await session.execute(select(Ticket.status, func.count()).group_by(Ticket.status))).all())
    return {
        "counts": {s: counts.get(s, 0) for s in STATUSES},
        "tickets": [row(t, student, code, assignee) for t, student, code, assignee in rows],
    }


def can_see_records(viewer: User, ticket: Ticket, resource: Resource) -> bool:
    """P8: the permission matrix's TICKET_STUDENT scope, applied to one ticket."""
    scope = scope_for(viewer.role, resource)
    if scope == Scope.ALL:
        return True
    if scope == Scope.TICKET_STUDENT:
        return ticket.status != "resolved"
    return False


async def detail(session: AsyncSession, viewer: User, ticket_id: int) -> dict:
    """P3: everything support needs to answer without asking the student again."""
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketError("Ticket not found.", 404)
    student = await session.get(User, ticket.student_id)
    course = await session.get(Course, ticket.course_id) if ticket.course_id else None
    assignee = await session.get(User, ticket.assigned_to) if ticket.assigned_to else None
    out = row(ticket, student.full_name if student else None, course.code if course else None)
    out["assigned_to"] = assignee.full_name if assignee else None
    out["draft"] = ticket.draft
    out["course_id"] = ticket.course_id
    out["kb_allowed"] = ticket.category == "academic"
    out["chat"] = await _chat_context(session, ticket)
    out["student_context"] = await _student_context(session, viewer, ticket, student)
    out["similar"] = await similar(session, ticket)
    return out


async def _chat_context(session: AsyncSession, ticket: Ticket) -> dict | None:
    if ticket.doubt_id is None:
        return None
    doubt = await session.get(Doubt, ticket.doubt_id)
    if doubt is None:
        return None
    sources = []
    for s in doubt.sources or []:
        text = None
        if s.get("faq_id"):
            faq = await session.get(FaqEntry, s["faq_id"])
            text = f"Q: {faq.question}\nA: {faq.answer}" if faq else None
        elif s.get("document_id") is not None:
            text = await session.scalar(
                select(Chunk.text).where(Chunk.document_id == s["document_id"], Chunk.chunk_index == s["chunk_index"])
            )
        sources.append({**s, "text": text})
    return {
        "question": doubt.question,
        "search_query": doubt.search_query,
        "answer": doubt.answer,
        "status": doubt.status,
        "intent": doubt.intent,
        "route": doubt.route,
        "confidence": doubt.confidence,
        "top_score": doubt.top_score,
        "top_rerank_score": doubt.top_rerank_score,
        "feedback": doubt.feedback,
        "feedback_comment": doubt.feedback_comment,
        "sources": sources,
        "asked_at": doubt.created_at.isoformat() if doubt.created_at else None,
    }


async def _student_context(session: AsyncSession, viewer: User, ticket: Ticket, student: User | None) -> dict:
    if student is None:
        return {"visible": False, "note": "The student no longer exists."}
    if not can_see_records(viewer, ticket, Resource.STUDENT_RECORDS):
        return {
            "visible": False,
            "name": student.full_name,
            "note": "This ticket is resolved, so the student's records are no longer shown (support sees a "
            "student's data only through an open ticket).",
        }
    enrollments = (
        await session.execute(
            select(Course.code, Course.title, Enrollment.status, Enrollment.progress_pct)
            .join(Course, Course.id == Enrollment.course_id)
            .where(Enrollment.student_id == student.id)  # scope: TICKET_STUDENT
            .order_by(Course.code)
        )
    ).all()
    out = {
        "visible": True,
        "name": student.full_name,
        "email": student.email,
        "city": student.city,
        "joined_at": student.joined_at.isoformat() if student.joined_at else None,
        "enrollments": [{"code": c, "title": t, "status": s.value, "progress_pct": p} for c, t, s, p in enrollments],
    }
    # Only what this kind of ticket needs: a course question doesn't need the student's payments.
    if ticket.category == "payment" and can_see_records(viewer, ticket, Resource.PAYMENTS):
        payments = (
            await session.execute(
                select(Payment, Course.code)
                .join(Course, Course.id == Payment.course_id)
                .where(Payment.student_id == student.id)
                .order_by(Payment.created_at.desc())
                .limit(5)
            )
        ).all()
        out["payments"] = [
            {
                "course_code": code,
                "amount_inr": p.amount_inr,
                "status": p.status.value,
                "method": p.method.value,
                "failure_reason": p.failure_reason,
                "at": p.created_at.isoformat(),
            }
            for p, code in payments
        ]
    if ticket.category == "login":
        logins = (
            await session.scalars(
                select(LoginEvent)
                .where(LoginEvent.user_id == student.id)
                .order_by(LoginEvent.occurred_at.desc())
                .limit(10)
            )
        ).all()
        out["logins"] = [
            {"at": e.occurred_at.isoformat(), "success": e.success, "reason": e.failure_reason, "device": e.device}
            for e in logins
        ]
    return out


# ---------------------------------------------------------------------------
# Similar tickets (P7) and embeddings
# ---------------------------------------------------------------------------


async def ensure_vectors(session: AsyncSession, tickets: list[Ticket], user: User | None) -> None:
    """Embed the subjects that have no vector yet, in one request. Done lazily (when support opens a ticket),
    so chatting never waits for it and a ticket nobody opens costs nothing."""
    missing = [t for t in tickets if not t.question_vec]
    if not missing:
        return
    result = await embed_texts(session, [t.subject for t in missing], feature="ticket_embed", user=user)
    for t, vec in zip(missing, result.vectors, strict=True):
        t.question_vec = vec


async def similar(session: AsyncSession, ticket: Ticket, k: int = 3) -> dict:
    """Resolved tickets that asked the same thing, so support can reuse an answer."""
    try:
        await ensure_vectors(session, [ticket], None)
    except Exception as exc:  # noqa: BLE001 - the ticket is still readable without its neighbours
        log.warning("Could not embed ticket %s: %s", ticket.id, exc)
        return {"available": False, "tickets": []}
    resolved = (
        await session.scalars(
            select(Ticket).where(
                Ticket.status == "resolved",
                Ticket.id != ticket.id,
                Ticket.category == ticket.category,
                Ticket.question_vec.is_not(None),
            )
        )
    ).all()
    found = vectors.nearest(
        ticket.question_vec, [(t, t.question_vec) for t in resolved], get_settings().similar_ticket_min, k
    )
    return {
        "available": True,
        "tickets": [
            {"id": t.id, "subject": t.subject, "resolution": t.resolution, "similarity": round(sim, 3)}
            for t, sim in found
        ],
    }


# ---------------------------------------------------------------------------
# Working a ticket
# ---------------------------------------------------------------------------


async def claim(session: AsyncSession, user: User, ticket_id: int) -> Ticket:
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketError("Ticket not found.", 404)
    if ticket.status == "resolved":
        raise TicketError("This ticket is already resolved.", 409)
    ticket.status, ticket.assigned_to = "in_progress", user.id
    return ticket


async def resolve(session: AsyncSession, user: User, ticket_id: int, resolution: str, save_to_kb: bool) -> Ticket:
    """P4-P6. The resolution is what the student sees. save_to_kb puts a COURSE answer into the knowledge
    base; login and payment answers are about one person's account and never go there."""
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketError("Ticket not found.", 404)
    if ticket.status == "resolved":
        raise TicketError("This ticket is already resolved.", 409)
    resolution = resolution.strip()
    if not resolution:
        raise TicketError("Write the answer the student will see.")
    if save_to_kb:
        if ticket.category != "academic":
            raise TicketError("Only course questions go into the knowledge base, not account problems.")
        if ticket.course_id is None:
            raise TicketError("Pick the course this answer belongs to before saving it to the knowledge base.")
        await ensure_vectors(session, [ticket], user)  # an LLMError here stops the resolve: nothing half-saved
        session.add(
            FaqEntry(
                course_id=ticket.course_id,
                question=_question_only(ticket.subject),
                answer=resolution,
                question_vec=ticket.question_vec,
                ticket_id=ticket.id,
                created_by=user.id,
            )
        )
    ticket.resolution, ticket.saved_to_kb = resolution, save_to_kb
    ticket.status, ticket.resolved_by, ticket.resolved_at = "resolved", user.id, datetime.now(UTC)
    ticket.assigned_to = ticket.assigned_to or user.id
    return ticket


def _question_only(subject: str) -> str:
    return subject.split("\n\n", 1)[0].strip()


async def set_course(session: AsyncSession, ticket_id: int, course_id: int | None) -> Ticket:
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketError("Ticket not found.", 404)
    if course_id is not None and await session.get(Course, course_id) is None:
        raise TicketError("No such course.")
    ticket.course_id = course_id
    return ticket


async def summary(session: AsyncSession) -> dict:
    """Support dashboard numbers."""
    by_status = dict((await session.execute(select(Ticket.status, func.count()).group_by(Ticket.status))).all())
    open_by_reason = dict(
        (
            await session.execute(
                select(Ticket.reason, func.count()).where(Ticket.status != "resolved").group_by(Ticket.reason)
            )
        ).all()
    )
    oldest = await session.scalar(select(func.min(Ticket.created_at)).where(Ticket.status != "resolved"))
    kb = await session.scalar(select(func.count()).select_from(FaqEntry).where(FaqEntry.active.is_(True)))
    return {
        "by_status": {s: by_status.get(s, 0) for s in STATUSES},
        "open_by_reason": {r: open_by_reason.get(r, 0) for r in REASONS},
        "oldest_open_at": oldest.isoformat() if oldest else None,
        "kb_entries": kb or 0,
    }


async def faq_list(session: AsyncSession, include_inactive: bool = False) -> list[dict]:
    Author = User.__table__.alias("author")
    query = (
        select(FaqEntry, Course.code, Author.c.full_name)
        .join(Course, Course.id == FaqEntry.course_id)
        .join(Author, Author.c.id == FaqEntry.created_by)
        .order_by(FaqEntry.id.desc())
    )
    if not include_inactive:
        query = query.where(FaqEntry.active.is_(True))
    rows = (await session.execute(query.limit(200))).all()
    return [
        {
            "id": f.id,
            "course_code": code,
            "question": f.question,
            "answer": f.answer,
            "ticket_id": f.ticket_id,
            "created_by": author,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "active": f.active,
        }
        for f, code, author in rows
    ]


def staff_only(user: User) -> None:
    if user.role not in (Role.support, Role.admin):
        raise TicketError("Only support staff and admins can work on tickets.", 403)
