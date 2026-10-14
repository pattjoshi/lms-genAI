"""Quiz generation (Phase 3c): a file or a topic -> draft multiple-choice questions.

    chunks (Postgres) -> pick passages -> LLM (structured output) -> validate -> shuffle -> draft quiz
                                                                                              |
                                          teacher approves / edits / rejects each question <--/
                                                                    |
                                                         publish -> students take it

Every question keeps the passage it was written from (T11): the teacher checks the answer
against the source in one glance, and students see where to read after a wrong answer.
"""

import logging
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.graph.extract import evidence_score, normalize_text
from app.llm.service import chat_structured
from app.llm.tracing import trace
from app.models import Chunk, Course, Document, DocumentStatus, Module, Quiz, QuizQuestion, Topic, User
from app.prompts.quiz import QUIZ_SYSTEM, QUIZ_USER, format_passages

log = logging.getLogger(__name__)

MIN_PASSAGE_CHARS = 200  # a heading-only chunk can't carry a question
BANNED_OPTIONS = {"all of the above", "none of the above", "both a and b", "all of these", "none of these"}


_SPACES = re.compile(r"\s+")


def tidy(text: str, max_chars: int) -> str:
    """Single spaces, trimmed, capped. (Unlike concept names, sentences keep their full stop.)"""
    return _SPACES.sub(" ", text).strip()[:max_chars]


class QuizError(Exception):
    """Can't generate: nothing indexed, or no question survived the checks. HTTP 422."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# 1. Output schema. Field descriptions are part of the prompt; no defaults (strict mode).
# ---------------------------------------------------------------------------


class DraftQuestion(BaseModel):
    question: str = Field(description="The question, one or two sentences.")
    options: list[str] = Field(description="Exactly 4 answer choices, without letters like 'A)'.")
    correct_option: int = Field(description="0-based index of the correct choice in options.")
    explanation: str = Field(description="Why the correct option is right, based on the passage.")
    passage: int = Field(description="Number of the passage the question comes from.")
    quote: str = Field(description="Under 30 words copied word for word from that passage that show the answer.")
    difficulty: Literal["easy", "medium", "hard"]


class QuizDraft(BaseModel):
    questions: list[DraftQuestion]


# ---------------------------------------------------------------------------
# 2. Passages: what the model reads
# ---------------------------------------------------------------------------


@dataclass
class Passage:
    chunk_id: int
    document_id: int
    file_name: str
    chunk_index: int
    page: int | None
    section: str | None
    topic: str | None
    text: str


def chunk_body(chunk_text: str, section: str | None) -> str:
    """The chunker prefixes each chunk with its heading; keep the text after it."""
    if section and chunk_text.startswith(section + "\n"):
        return chunk_text[len(section) + 1 :]
    return chunk_text


def pick_passages(passages: list[Passage], max_passages: int) -> list[Passage]:
    """Spread evenly over the material, so a 40-chunk file isn't quizzed on its first pages only.
    Very short chunks (a heading, a caption) are skipped while there are enough longer ones."""
    long = [p for p in passages if len(p.text) >= MIN_PASSAGE_CHARS]
    pool = long if len(long) >= min(max_passages, len(passages)) else passages
    if len(pool) <= max_passages:
        return pool
    step = len(pool) / max_passages
    return [pool[int(i * step + step / 2)] for i in range(max_passages)]


# ---------------------------------------------------------------------------
# 3. Validation: strict JSON guarantees the shape; these checks are about the content
# ---------------------------------------------------------------------------


@dataclass
class CheckedQuestion:
    question: str
    options: list[str]
    correct_index: int
    explanation: str
    difficulty: str
    passage: Passage
    quote: str


def _strip_letter(option: str) -> str:
    """'B) Gradient descent' -> 'Gradient descent' (models add letters despite being told not to)."""
    o = option.strip()
    if len(o) > 3 and o[0].upper() in "ABCD" and o[1] in ").:" and o[2] == " ":
        return o[3:].strip()
    return o


def shuffle_options(options: list[str], correct: int, seed: str) -> tuple[list[str], int]:
    """LLMs put the right answer in the first two slots far more often than 1 in 4. Shuffling
    fixes the bias. Seeded by the question text, so the same question always shuffles the same way."""
    order = list(range(len(options)))
    random.Random(seed).shuffle(order)
    return [options[i] for i in order], order.index(correct)


def check_questions(
    draft: QuizDraft, passages: list[Passage], limit: int, min_quote: float = 0.8
) -> tuple[list[CheckedQuestion], list[str]]:
    """Returns (questions kept, reasons for the ones dropped)."""
    kept: list[CheckedQuestion] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for q in draft.questions:
        text = tidy(q.question, 600)
        options = [tidy(_strip_letter(o), 300) for o in q.options]
        label = text[:60] or "(empty question)"
        if not text:
            dropped.append("empty question")
            continue
        if len(options) != 4 or any(not o for o in options):
            dropped.append(f"needs exactly 4 non-empty options: {label}")
            continue
        if len({normalize_text(o) for o in options}) != 4:
            dropped.append(f"two options are the same: {label}")
            continue
        if any(normalize_text(o) in BANNED_OPTIONS for o in options):
            dropped.append(f"'all/none of the above' option: {label}")
            continue
        if not 0 <= q.correct_option < 4:
            dropped.append(f"correct option out of range: {label}")
            continue
        if not 1 <= q.passage <= len(passages):
            dropped.append(f"unknown passage {q.passage}: {label}")
            continue
        passage = passages[q.passage - 1]
        if evidence_score(q.quote, passage.text) < min_quote:
            # The proof isn't in the course text: the model answered from general knowledge,
            # or misread the passage. Not grounded -> not in the quiz.
            dropped.append(f"quote not in passage {q.passage}: {label}")
            continue
        key = normalize_text(text)
        if key in seen:
            dropped.append(f"duplicate: {label}")
            continue
        seen.add(key)
        options, correct = shuffle_options(options, q.correct_option, text)
        kept.append(
            CheckedQuestion(
                question=text,
                options=options,
                correct_index=correct,
                explanation=tidy(q.explanation, 800),
                difficulty=q.difficulty,
                passage=passage,
                quote=tidy(q.quote, 400),
            )
        )
    if len(kept) > limit:
        dropped += [f"over the limit of {limit}: {q.question[:60]}" for q in kept[limit:]]
    return kept[:limit], dropped


def main_topic(questions: list[CheckedQuestion]) -> str | None:
    """The topic most questions came from, if it's a clear majority (a quiz about one topic
    then counts towards that topic on the student's dashboard)."""
    topics = Counter(q.passage.topic for q in questions if q.passage.topic)
    if not topics:
        return None
    name, count = topics.most_common(1)[0]
    return name if count * 2 > len(questions) else None


# ---------------------------------------------------------------------------
# 4. Running it
# ---------------------------------------------------------------------------


async def _passages_for(session: AsyncSession, course: Course, document: Document | None, topic: Topic | None):
    query = (
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Document.course_id == course.id,
            Document.status == DocumentStatus.ready,
            Document.superseded_at.is_(None),  # current versions only
        )
        .order_by(Document.id, Chunk.chunk_index)
    )
    if document is not None:
        query = query.where(Document.id == document.id)
    if topic is not None:
        # Tagged with the topic, or under a heading with its name (in case tagging picked another)
        query = query.where(or_(Chunk.topic == topic.name, func.lower(Chunk.section) == topic.name.lower()))
    rows = (await session.execute(query)).all()
    return [
        Passage(
            chunk_id=c.id,
            document_id=d.id,
            file_name=d.file_name,
            chunk_index=c.chunk_index,
            page=c.page,
            section=c.section,
            topic=c.topic,
            text=chunk_body(c.text, c.section),
        )
        for c, d in rows
    ]


async def generate_quiz(
    session: AsyncSession,
    *,
    course: Course,
    user: User,
    document: Document | None = None,
    topic: Topic | None = None,
    num_questions: int = 5,
    title: str | None = None,
) -> tuple[Quiz, list[str]]:
    """Generate a DRAFT quiz from one file or one topic. Returns (quiz, reasons questions were dropped)."""
    s = get_settings()
    num_questions = max(1, min(num_questions, s.quiz_max_questions))
    about = f"file: {document.file_name}" if document else f"topic: {topic.name}" if topic else "the course"

    passages = await _passages_for(session, course, document, topic)
    if not passages:
        raise QuizError(f"No indexed course text for {about}. Upload a file or wait until it is ready.")
    passages = pick_passages(passages, s.quiz_max_passages)
    for p in passages:
        p.text = p.text[: s.quiz_passage_chars]

    with trace("generate_quiz", user, "quizzes", input={"about": about, "questions": num_questions}) as root:
        messages = [
            SystemMessage(QUIZ_SYSTEM.format(n=num_questions)),
            HumanMessage(
                QUIZ_USER.format(course=course.title, about=about, passages=format_passages([p.text for p in passages]))
            ),
        ]
        draft, result = await chat_structured(
            session,
            messages=messages,
            schema=QuizDraft,
            feature="quiz_generate",
            user=user,
            max_tokens=s.quiz_max_output_tokens,
        )
        questions, dropped = check_questions(draft, passages, num_questions)
        root.update(output={"kept": len(questions), "dropped": dropped, "cost_usd": result.cost_usd})
    log.info("Quiz for %s: %d kept, dropped %s", about, len(questions), dropped)
    if not questions:
        raise QuizError("None of the AI's questions could be checked against your material. Try again.")

    topic_id = topic.id if topic else None
    if topic_id is None and (name := main_topic(questions)):
        topic_id = await session.scalar(
            select(Topic.id)
            .join(Module, Module.id == Topic.module_id)
            .where(Module.course_id == course.id, Topic.name == name)
        )
    if document:
        default_title = PurePath(document.file_name).stem.replace("_", " ") + " quiz"
    else:
        default_title = f"{topic.name} quiz" if topic else ""
    quiz = Quiz(
        course_id=course.id,
        topic_id=topic_id,
        document_id=document.id if document else None,
        title=tidy(title or default_title, 160) or "Quiz",
        source_label=about[:255],
        status="draft",
        created_by=user.id,
        created_at=datetime.now(UTC),
        generation_cost_usd=round(result.cost_usd, 6),
    )
    session.add(quiz)
    await session.flush()
    for i, q in enumerate(questions, start=1):
        p = q.passage
        session.add(
            QuizQuestion(
                quiz_id=quiz.id,
                position=i,
                question=q.question,
                options=q.options,
                correct_index=q.correct_index,
                explanation=q.explanation,
                difficulty=q.difficulty,
                status="draft",
                chunk_id=p.chunk_id,
                source={
                    "document_id": p.document_id,
                    "file_name": p.file_name,
                    "page": p.page,
                    "section": p.section,
                    "chunk_index": p.chunk_index,
                    "text": p.text,
                    "quote": q.quote,
                },
            )
        )
    await session.commit()
    return quiz, dropped


# ---------------------------------------------------------------------------
# 5. Grading: done on the server, so the right answers never reach the browser before submitting
# ---------------------------------------------------------------------------


def grade(questions: list[QuizQuestion], answers: dict[int, int | None]) -> tuple[int, list[dict]]:
    """-> (score 0-100, one result per question). Unanswered counts as wrong."""
    results = []
    for q in questions:
        chosen = answers.get(q.id)
        results.append({"question_id": q.id, "chosen": chosen, "correct": chosen == q.correct_index})
    right = sum(r["correct"] for r in results)
    return (round(100 * right / len(results)) if results else 0), results
