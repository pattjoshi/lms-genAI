"""Practice questions in the chat (Phase 4, S13 + S14).

"Quiz me on X" (or on my weak topics) -> 3 multiple-choice questions written from the course passages
about X, with the same checks as teacher quizzes (Phase 3c: quote in the passage, 4 distinct options,
shuffled). Unlike quizzes, nobody reviews them first: they are for practice only and never count as a
score. That trade-off is why the checks in code matter, and why every answer shows its source.

Answers stay on the server; the student gets the right answer and explanation after answering, and the
result goes into memory (practice_wrong / practice_right), which updates their weak topics.
"""

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.memory import remember
from app.config import get_settings
from app.graph.names import concept_key
from app.models import Chunk, Course, Document, DocumentStatus, Module, PracticeSet, Topic, User
from app.quiz.generate import Passage, chunk_body, draft_questions, passages_for
from app.scopes import readable_course_ids


class PracticeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Material:
    course: Course
    topic: str
    passages: list[Passage]


async def find_material(session: AsyncSession, user: User, topic: str) -> Material | None:
    """Course passages about `topic` in the user's courses: a catalogue topic with that name first,
    then chunks whose heading or tag contains the words."""
    course_ids = await readable_course_ids(session, user)
    if not course_ids:
        return None
    key = concept_key(topic)
    topics = (
        await session.execute(
            select(Topic, Course)
            .join(Module, Module.id == Topic.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Course.id.in_(course_ids))
        )
    ).all()
    exact = [(t, c) for t, c in topics if concept_key(t.name) == key]
    partial = [(t, c) for t, c in topics if key and (key in concept_key(t.name) or concept_key(t.name) in key)]
    for t, c in exact + partial:
        if passages := await passages_for(session, c, None, t):
            return Material(c, t.name, passages)

    like = f"%{topic.strip()[:80]}%"
    rows = (
        await session.execute(
            select(Chunk, Document)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Document.course_id.in_(course_ids),
                Document.status == DocumentStatus.ready,
                Document.superseded_at.is_(None),
                or_(Chunk.section.ilike(like), Chunk.topic.ilike(like)),
            )
            .order_by(Document.id, Chunk.chunk_index)
        )
    ).all()
    if not rows:
        return None
    course_id = rows[0][1].course_id  # one course per practice set
    passages = [
        Passage(c.id, d.id, d.file_name, c.chunk_index, c.page, c.section, c.topic, chunk_body(c.text, c.section))
        for c, d in rows
        if d.course_id == course_id
    ]
    return Material(await session.get(Course, course_id), topic, passages)


async def create_set(session: AsyncSession, user: User, topic: str) -> PracticeSet:
    material = await find_material(session, user, topic)
    if material is None:
        raise PracticeError(f"I couldn't find course material about “{topic}” in your courses.")
    n = get_settings().practice_questions
    questions, _, cost = await draft_questions(
        session,
        course=material.course,
        user=user,
        passages=material.passages,
        about=f"topic: {material.topic}",
        n=n,
        feature="practice_generate",
    )
    if not questions:
        raise PracticeError("The questions I wrote didn't pass the checks against your material. Try again.")
    practice = PracticeSet(
        student_id=user.id,
        course_id=material.course.id,
        topic=material.topic,
        questions=[
            {
                "question": q.question,
                "options": q.options,
                "correct_index": q.correct_index,
                "explanation": q.explanation,
                "difficulty": q.difficulty,
                "source": {"file_name": q.passage.file_name, "page": q.passage.page, "section": q.passage.section},
            }
            for q in questions
        ],
        answers={},
        cost_usd=round(cost, 6),
    )
    session.add(practice)
    await session.flush()
    return practice


def public(practice: PracticeSet, course_code: str | None = None) -> dict:
    """What the browser gets: questions without answers, plus the results of questions already answered."""
    out = []
    for i, q in enumerate(practice.questions):
        item = {"index": i, "question": q["question"], "options": q["options"], "difficulty": q["difficulty"]}
        if str(i) in (practice.answers or {}):
            item["result"] = result_of(practice, i)
        out.append(item)
    return {"id": practice.id, "topic": practice.topic, "course_code": course_code, "questions": out}


def result_of(practice: PracticeSet, index: int) -> dict:
    q = practice.questions[index]
    chosen = practice.answers[str(index)]
    return {
        "chosen": chosen,
        "correct": chosen == q["correct_index"],
        "correct_index": q["correct_index"],
        "explanation": q["explanation"],
        "source": q["source"],
    }


async def answer(session: AsyncSession, user: User, practice_id: int, index: int, chosen: int) -> dict:
    practice = await session.get(PracticeSet, practice_id)
    if practice is None or practice.student_id != user.id:
        raise PracticeError("Practice not found.")
    if not 0 <= index < len(practice.questions) or not 0 <= chosen < 4:
        raise PracticeError("No such question or option.")
    if str(index) in (practice.answers or {}):
        return result_of(practice, index)  # answered already: same result, memory not counted twice
    practice.answers = {**(practice.answers or {}), str(index): chosen}  # new dict: JSON change tracking
    result = result_of(practice, index)
    await remember(session, user, practice.topic, "practice_right" if result["correct"] else "practice_wrong")
    await session.commit()
    return result
