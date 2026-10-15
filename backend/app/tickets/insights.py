"""Teacher insights (T13, T14): what students ask, grouped by meaning, and what the material can't answer.

"How do I stop overfitting?" and "my model memorises the training set, help" are the same question in
different words. Counting exact strings would miss that, so each question is embedded once (the vector is
kept on the doubt row) and similar questions are grouped (vectors.group, cosine >= INSIGHTS_GROUP_SIMILARITY).

    Most asked doubts   every course question, grouped; the biggest groups first
    Content gaps        the questions the AI could not answer from the material, or answered with low
                        confidence, or that got a 👎: grouped the same way. Each group is a page the
                        teacher could add to the course.

Privacy: teachers see questions and counts, never who asked. A course is the course of the top retrieved
passage; questions with no passage at all can't be placed and are left out.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.service import embed_texts
from app.models import Course, Doubt, Role, Ticket, User
from app.scopes import manageable_course_ids
from app.tickets import vectors

MAX_DOUBTS = 500  # per request: enough for a course's month, small enough to group in Python


def course_of(doubt: Doubt) -> str | None:
    for s in doubt.sources or []:
        if s.get("course_code"):
            return s["course_code"]
    return None


def is_gap(doubt: Doubt) -> bool:
    return doubt.status == "no_context" or doubt.confidence == "low" or doubt.feedback == -1


def label_of(members: list[Doubt], vecs: dict[int, list[float]], total: list[float]) -> str:
    """The question closest to the group's centre: the most typical wording."""
    return max(members, key=lambda d: vectors.cosine(vecs[d.id], total)).question


TICKET_ORDER = ["open", "in_progress", "resolved", "in knowledge base"]


def _furthest(states: list[str]) -> str | None:
    """The group's most advanced ticket: one answer in the knowledge base covers the whole group."""
    return max(states, key=TICKET_ORDER.index) if states else None


def summarise(groups: list[vectors.Group], vecs: dict[int, list[float]], kb_by_doubt: dict[int, str]) -> list[dict]:
    out = []
    for g in groups:
        members: list[Doubt] = g.members
        courses = Counter(course_of(d) for d in members)
        examples = list(dict.fromkeys(d.question for d in members))[:4]
        out.append(
            {
                "label": label_of(members, vecs, g.total),
                "count": len(members),
                "students": len({d.student_id for d in members}),
                "course_code": courses.most_common(1)[0][0],
                "examples": examples,
                "unanswered": sum(1 for d in members if d.status == "no_context"),
                "low_confidence": sum(1 for d in members if d.confidence == "low"),
                "thumbs_down": sum(1 for d in members if d.feedback == -1),
                "last_asked": max(d.created_at for d in members).isoformat(),
                "ticket_status": _furthest([kb_by_doubt[d.id] for d in members if d.id in kb_by_doubt]),
            }
        )
    return out


async def insights(session: AsyncSession, user: User, days: int | None = None, course_code: str | None = None) -> dict:
    s = get_settings()
    days = days or s.insights_days
    since = datetime.now(UTC) - timedelta(days=days)
    if user.role == Role.admin:
        codes = set((await session.scalars(select(Course.code))).all())
    else:
        ids = await manageable_course_ids(session, user)  # teacher: own courses only
        codes = set((await session.scalars(select(Course.code).where(Course.id.in_(ids)))).all()) if ids else set()
    if course_code:
        codes &= {course_code.upper()}

    doubts = (
        await session.scalars(
            select(Doubt)
            .where(
                Doubt.created_at >= since,
                or_(Doubt.intent.is_(None), Doubt.intent == "doubt"),
                Doubt.status.in_(["answered", "no_context"]),
            )
            .order_by(Doubt.id.desc())
            .limit(MAX_DOUBTS * 2)
        )
    ).all()
    # Hidden doubts count too: a student removing a question from their history doesn't make it unasked.
    doubts = [d for d in doubts if course_of(d) in codes][:MAX_DOUBTS]

    # Embed the questions that don't have a vector yet (once; kept on the row).
    missing = [d for d in doubts if not d.question_vec]
    embed_cost = 0.0
    if missing:
        result = await embed_texts(session, [d.question for d in missing], feature="insights_embed", user=user)
        for d, vec in zip(missing, result.vectors, strict=True):
            d.question_vec = vec
        embed_cost = result.cost_usd
        await session.commit()

    vecs = {d.id: d.question_vec for d in doubts}
    ticket_rows = (
        await session.execute(
            select(Ticket.doubt_id, Ticket.status, Ticket.saved_to_kb).where(
                Ticket.doubt_id.in_([d.id for d in doubts])
            )
        )
    ).all()
    ticket_state = {doubt_id: ("in knowledge base" if kb else status) for doubt_id, status, kb in ticket_rows}

    threshold = s.insights_group_similarity
    asked = vectors.group([(d, vecs[d.id]) for d in doubts], threshold)
    gaps = vectors.group([(d, vecs[d.id]) for d in doubts if is_gap(d)], threshold)
    return {
        "days": days,
        "courses": sorted(codes),
        "questions": len(doubts),
        "threshold": threshold,
        "embedded_now": len(missing),
        "embed_cost_usd": embed_cost,
        "most_asked": summarise(asked[:15], vecs, ticket_state),
        "gaps": summarise(gaps[:15], vecs, ticket_state),
    }
