"""What the assistant remembers about a student (Phase 4, S11 + S12).

Two kinds of memory, like in most agent designs:

    short-term   the current chat: earlier turns of the same conversation (chat.py `_history`)
    long-term    across chats, in the database:
                   - quiz scores per topic (quiz_attempts, already there)
                   - topics the student said they don't understand, or practised (learner_topics)

Long-term memory here is FACTS in tables, not a summary the LLM wrote about the student. Facts can be
queried, shown to the student ("why does it think I'm weak at this?"), and corrected; an LLM-written
profile can drift and is hard to audit.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.graph.names import clean_name, concept_key
from app.models import Course, LearnerTopic, Module, Quiz, QuizAttempt, Topic, User


@dataclass
class TopicScore:
    name: str
    course_code: str
    avg: int
    attempts: int


@dataclass
class WeakTopic:
    name: str
    course_code: str | None
    why: str  # shown to the student: where the assistant got this from
    avg_score: int | None = None


async def topic_scores(session: AsyncSession, user: User) -> dict[str, TopicScore]:
    """The student's quiz average per topic, keyed by concept key (so it joins with graph concepts)."""
    rows = (
        await session.execute(
            select(Topic.name, Course.code, func.avg(QuizAttempt.score_pct), func.count())
            .select_from(QuizAttempt)
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .join(Topic, Topic.id == Quiz.topic_id)
            .join(Module, Module.id == Topic.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(QuizAttempt.student_id == user.id)  # scope: OWN
            .group_by(Topic.name, Course.code)
        )
    ).all()
    return {concept_key(n): TopicScore(n, c, round(avg), k) for n, c, avg, k in rows}


async def remember(session: AsyncSession, user: User, topic: str, kind: str) -> None:
    """Count one more 'asked_path' / 'practice_wrong' / 'practice_right' for this topic. Caller commits."""
    name = clean_name(topic, 120)
    key = concept_key(name)[:120]
    if not key:
        return
    row = await session.scalar(
        select(LearnerTopic).where(
            LearnerTopic.student_id == user.id, LearnerTopic.key == key, LearnerTopic.kind == kind
        )
    )
    now = datetime.now(UTC)
    if row is None:
        session.add(LearnerTopic(student_id=user.id, topic=name, key=key, kind=kind, count=1, last_at=now))
    else:
        row.count += 1
        row.last_at = now


def merge_weak(scores: dict[str, TopicScore], struggles: list[LearnerTopic], weak_below: int) -> list[WeakTopic]:
    """Quiz scores + what the student told us -> one ranked list. Pure function (tested).

    - a quiz average below `weak_below` makes a topic weak
    - saying "I don't understand X" or getting practice on X wrong makes it weak too, until the student
      gets as many practice questions on it right as they got wrong
    """
    out: dict[str, WeakTopic] = {}
    for key, s in sorted(scores.items(), key=lambda kv: kv[1].avg):
        if s.avg < weak_below:
            out[key] = WeakTopic(s.name, s.course_code, f"quiz average {s.avg}%", s.avg)

    by_key: dict[str, dict[str, LearnerTopic]] = {}
    for r in struggles:
        by_key.setdefault(r.key, {})[r.kind] = r
    ranked = sorted(by_key.items(), key=lambda kv: -max(r.last_at.timestamp() for r in kv[1].values()))
    for key, kinds in ranked:
        asked = kinds.get("asked_path")
        wrong = kinds["practice_wrong"].count if "practice_wrong" in kinds else 0
        right = kinds["practice_right"].count if "practice_right" in kinds else 0
        if right >= max(wrong, 1) and (scores.get(key) is None or scores[key].avg >= weak_below):
            continue  # practised it and got it right: not weak any more
        if not asked and not wrong:
            continue
        name = next(iter(kinds.values())).topic
        reasons = []
        if asked:
            reasons.append("you said you don't understand it" + (f" ({asked.count}×)" if asked.count > 1 else ""))
        if wrong:
            reasons.append(f"{wrong} practice answer{'s' if wrong > 1 else ''} wrong")
        if key in out:
            out[key].why += "; " + "; ".join(reasons)
        else:
            out[key] = WeakTopic(name, None, "; ".join(reasons))
    return list(out.values())


async def weak_topics(session: AsyncSession, user: User, limit: int = 5) -> list[WeakTopic]:
    scores = await topic_scores(session, user)
    struggles = (await session.scalars(select(LearnerTopic).where(LearnerTopic.student_id == user.id))).all()
    return merge_weak(scores, list(struggles), get_settings().weak_topic_score)[:limit]
