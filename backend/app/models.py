"""Relational schema (Postgres).

Table and column `comment=`s are stored in Postgres itself. In Phase 6 the SQL agent
reads them to understand the schema, so keep them accurate when you change a table.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _enum(enum_cls: type[StrEnum]) -> Enum:
    # Stored as VARCHAR + CHECK constraint: readable in plain SQL, no custom PG types.
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


class Role(StrEnum):
    student = "student"
    teacher = "teacher"
    admin = "admin"
    support = "support"


class Difficulty(StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class EnrollmentStatus(StrEnum):
    active = "active"
    completed = "completed"
    dropped = "dropped"


class PaymentStatus(StrEnum):
    success = "success"
    failed = "failed"
    pending = "pending"
    refunded = "refunded"


class PaymentMethod(StrEnum):
    upi = "upi"
    card = "card"
    netbanking = "netbanking"
    wallet = "wallet"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"comment": "Everyone who can log in: students, teachers, admins, support staff."}

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    role: Mapped[Role] = mapped_column(_enum(Role), comment="student | teacher | admin | support")
    city: Mapped[str] = mapped_column(String(80))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = {"comment": "A course. Each course is owned by exactly one teacher."}

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, comment="Short code, e.g. DL301")
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), comment="users.id of the owning teacher")
    price_inr: Mapped[int] = mapped_column(Integer, comment="List price in Indian rupees")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    modules: Mapped[list["Module"]] = relationship(back_populates="course", order_by="Module.position")


class Module(Base):
    __tablename__ = "modules"
    __table_args__ = {"comment": "A unit inside a course, in teaching order."}

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    position: Mapped[int] = mapped_column(Integer, comment="1-based order inside the course")
    title: Mapped[str] = mapped_column(String(120))

    course: Mapped[Course] = relationship(back_populates="modules")
    topics: Mapped[list["Topic"]] = relationship(back_populates="module", order_by="Topic.position")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = {"comment": "A single topic inside a module. Each topic has one quiz."}

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"))
    position: Mapped[int] = mapped_column(Integer, comment="1-based order inside the module")
    name: Mapped[str] = mapped_column(String(120))
    difficulty: Mapped[Difficulty] = mapped_column(_enum(Difficulty), comment="easy | medium | hard")

    module: Mapped[Module] = relationship(back_populates="topics")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id"),
        {"comment": "A student enrolled in a course."},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[EnrollmentStatus] = mapped_column(_enum(EnrollmentStatus), comment="active | completed | dropped")
    progress_pct: Mapped[int] = mapped_column(Integer, comment="0-100, share of topics covered")


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = {"comment": "One quiz per topic."}

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    title: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = {"comment": "A student's attempt at a quiz. Students may attempt a quiz more than once."}

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    score_pct: Mapped[int] = mapped_column(Integer, comment="0-100. Below 50 counts as failed.")
    time_taken_sec: Mapped[int] = mapped_column(Integer)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = {"comment": "Course purchase payments, including failed and refunded ones."}

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    amount_inr: Mapped[int] = mapped_column(Integer)
    status: Mapped[PaymentStatus] = mapped_column(_enum(PaymentStatus), comment="success | failed | pending | refunded")
    method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod), comment="upi | card | netbanking | wallet")
    failure_reason: Mapped[str | None] = mapped_column(String(200), comment="Only set when status = failed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginEvent(Base):
    __tablename__ = "login_events"
    __table_args__ = {"comment": "Every login attempt, successful or not."}

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    success: Mapped[bool] = mapped_column(Boolean)
    failure_reason: Mapped[str | None] = mapped_column(
        String(40), comment="wrong_password | account_locked | otp_expired; null on success"
    )
    device: Mapped[str] = mapped_column(String(20), comment="web | android | ios")


class LLMUsage(Base):
    __tablename__ = "llm_usage"
    __table_args__ = {
        "comment": "One row per LLM call: tokens, cost and latency. Feeds the budget guard and cost dashboard."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    feature: Mapped[str] = mapped_column(String(60), comment="Which feature made the call, e.g. hello, doubt_answer")
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=1, comment="1 = no retries were needed")
    status: Mapped[str] = mapped_column(String(20), comment="success | error")
    error_code: Mapped[str | None] = mapped_column(String(60))


# ---------------------------------------------------------------------------
# Phase 1: uploaded course files, their chunks, and students' doubts
# ---------------------------------------------------------------------------


class DocumentStatus(StrEnum):
    uploaded = "uploaded"
    parsing = "parsing"
    chunking = "chunking"
    embedding = "embedding"
    tagging = "tagging"
    indexing = "indexing"
    ready = "ready"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {
        "comment": "A course file uploaded by a teacher (PDF, DOCX, HTML or TXT) and its processing state."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    file_name: Mapped[str] = mapped_column(String(255), comment="Original file name shown in citations")
    file_type: Mapped[str] = mapped_column(String(10), comment="pdf | docx | html | txt")
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), comment="Content hash, used to reject duplicate uploads")
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[DocumentStatus] = mapped_column(_enum(DocumentStatus), default=DocumentStatus.uploaded)
    error: Mapped[str | None] = mapped_column(Text)
    num_pages: Mapped[int | None] = mapped_column(Integer, comment="PDF pages; null for other types")
    num_chunks: Mapped[int] = mapped_column(Integer, default=0)
    embed_tokens: Mapped[int] = mapped_column(Integer, default=0)
    embed_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Versioning: re-uploading a file with the same name in the same module creates v2, v3...
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", comment="1, 2, 3... for re-uploads of the same file name"
    )
    replaces_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), comment="The previous version this upload replaces"
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Set when a newer version went live; this version is no longer searchable"
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = {
        "comment": "A piece of a document as stored in Qdrant. Postgres keeps the text for preview and evals."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer, comment="0-based position inside the document")
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer, comment="1-based PDF page; null for other file types")
    section: Mapped[str | None] = mapped_column(String(255), comment="Heading the chunk falls under, if any")
    topic: Mapped[str | None] = mapped_column(String(120), comment="Auto-tagged topic name (topics.name)")
    difficulty: Mapped[str | None] = mapped_column(String(20))
    topic_score: Mapped[float | None] = mapped_column(
        Float, comment="Similarity to the tagged topic (1.0 = matched by heading)"
    )
    point_id: Mapped[str] = mapped_column(String(36), comment="Qdrant point id (UUID)")


class Doubt(Base):
    __tablename__ = "doubts"
    __table_args__ = {"comment": "Every question a student asked the assistant, with the answer and how it went."}

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), comment="answered | no_context | error")
    top_score: Mapped[float | None] = mapped_column(
        Float, comment="Best retrieval similarity; low = likely content gap"
    )
    sources: Mapped[list | None] = mapped_column(JSON, comment="Retrieved chunks shown as citations")
    conversation_id: Mapped[str | None] = mapped_column(
        String(64), index=True, comment="Chat the doubt belongs to; earlier turns help rewrite follow-ups"
    )
    search_query: Mapped[str | None] = mapped_column(
        Text, comment="What was actually searched, when a rewrite changed the question"
    )
    top_rerank_score: Mapped[float | None] = mapped_column(Float, comment="Best reranker relevance (0-1)")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Student removed it from their history (kept for anonymous analytics)"
    )
