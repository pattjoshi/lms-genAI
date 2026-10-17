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
    __table_args__ = {
        "comment": "A quiz. Seeded quizzes: one per topic, scores only. Phase 3: generated from a file or "
        "topic by the AI, with questions in quiz_questions, published by the teacher."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topics.id"), comment="Topic the quiz tests; null when a generated quiz spans several"
    )
    title: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Phase 3: generated quizzes
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), comment="Course the quiz belongs to")
    status: Mapped[str] = mapped_column(
        String(20),
        default="published",
        server_default="published",
        comment="draft (teacher reviewing, students can't see it) | published",
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), comment="Teacher who generated it; null for seeded quizzes"
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), comment="File the questions were generated from"
    )
    source_label: Mapped[str | None] = mapped_column(
        String(255), comment="What it was generated from, e.g. 'file: intro.pdf' or 'topic: Joins'"
    )
    generation_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = {
        "comment": "A multiple-choice question of a generated quiz, with the course passage it was written from."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, comment="1-based order inside the quiz")
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, comment="The 4 answer choices, in the order students see them")
    correct_index: Mapped[int] = mapped_column(Integer, comment="0-based index into options")
    explanation: Mapped[str] = mapped_column(Text, comment="Why the answer is right, shown after submitting")
    difficulty: Mapped[str] = mapped_column(String(20), comment="easy | medium | hard")
    status: Mapped[str] = mapped_column(
        String(20), default="draft", comment="draft | approved | rejected. Students only get approved questions"
    )
    edited: Mapped[bool] = mapped_column(Boolean, default=False, comment="A teacher changed the AI's text")
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"))
    source: Mapped[dict] = mapped_column(
        JSON,
        comment="Copy of the source passage: document_id, file_name, page, section, text, quote. Kept even "
        "when the file is re-processed or deleted",
    )


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = {"comment": "A student's attempt at a quiz. Students may attempt a quiz more than once."}

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    score_pct: Mapped[int] = mapped_column(Integer, comment="0-100. Below 50 counts as failed.")
    time_taken_sec: Mapped[int] = mapped_column(Integer)
    answers: Mapped[list | None] = mapped_column(
        JSON, comment="Generated quizzes: [{question_id, chosen, correct}]; null for seeded attempts"
    )


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
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="Langfuse trace of the request (Phase 7)")


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
    # Phase 3: concept extraction runs after indexing. It has its own status, so a failure
    # here never takes a file out of search.
    concepts_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        comment="pending | extracting | done | failed | off (concept extraction into the Neo4j graph)",
    )
    concepts_error: Mapped[str | None] = mapped_column(Text)
    num_concepts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="Concepts extracted from this file"
    )
    concepts_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", comment="LLM + embedding cost of the extraction"
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
    status: Mapped[str] = mapped_column(String(20), comment="answered | no_context | blocked (guardrail) | error")
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
    # Phase 4: every chat message is routed first; only "doubt" goes to RAG
    intent: Mapped[str | None] = mapped_column(
        String(20),
        comment="doubt | learning_path | practice | progress | support (null = before Phase 4, i.e. doubt)",
    )
    route: Mapped[dict | None] = mapped_column(
        JSON, comment="How the intent was decided: method (rules | embedding | llm), confidence, topic"
    )
    # Phase 5: the feedback loop
    confidence: Mapped[str | None] = mapped_column(String(10), comment="high | medium | low (course answers only)")
    feedback: Mapped[int | None] = mapped_column(Integer, comment="1 = thumbs up, -1 = thumbs down")
    feedback_comment: Mapped[str | None] = mapped_column(Text)
    question_vec: Mapped[list | None] = mapped_column(
        JSON, comment="Embedding of the question, filled when needed (teacher insights: grouping by meaning)"
    )
    # Phase 7: guardrails and tracing
    checks: Mapped[dict | None] = mapped_column(
        JSON, comment="Guardrail results: the input verdict and, for course answers, the output checks (citations)"
    )
    first_token_ms: Mapped[int | None] = mapped_column(Integer, comment="Time to the first streamed answer token")
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="Langfuse trace of this message")


# ---------------------------------------------------------------------------
# Phase 4: what the assistant remembers about a student, and practice questions
# ---------------------------------------------------------------------------


class LearnerTopic(Base):
    __tablename__ = "learner_topics"
    __table_args__ = (
        UniqueConstraint("student_id", "key", "kind"),
        {
            "comment": "Long-term memory: topics a student said they don't understand or practised. "
            "Together with quiz scores, this is what the assistant knows the student finds hard."
        },
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    topic: Mapped[str] = mapped_column(String(120), comment="Display name, as the student or the graph named it")
    key: Mapped[str] = mapped_column(String(120), comment="Normalised name, so 'Backprop' and 'backprop' match")
    kind: Mapped[str] = mapped_column(
        String(20), comment="asked_path (said they don't understand it) | practice_wrong | practice_right"
    )
    count: Mapped[int] = mapped_column(Integer, default=1)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeSet(Base):
    __tablename__ = "practice_sets"
    __table_args__ = {
        "comment": "AI-written practice questions for one student on one topic, created from the chat. "
        "Not reviewed by a teacher (unlike quizzes): practice only, never graded for the record."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    topic: Mapped[str] = mapped_column(String(120))
    questions: Mapped[list] = mapped_column(
        JSON, comment="[{question, options, correct_index, explanation, source}]; answers never sent before answering"
    )
    answers: Mapped[dict] = mapped_column(JSON, default=dict, comment="{question index: chosen option index}")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 4b: MCP access
# ---------------------------------------------------------------------------


class ApiToken(Base):
    __tablename__ = "api_tokens"
    __table_args__ = {
        "comment": "Personal access tokens for MCP clients (Claude Desktop, Cursor, MCP Inspector). Only a SHA-256 "
        "hash is stored; the token is shown once. A token acts as its user, with that user's role and scopes."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), comment="What the user called it, e.g. 'Claude Desktop'")
    prefix: Mapped[str] = mapped_column(String(16), comment="First characters, shown in the list to tell tokens apart")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpCall(Base):
    __tablename__ = "mcp_calls"
    __table_args__ = {"comment": "Audit log: one row per MCP tool call, resource read or refused request."}

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    token_id: Mapped[int | None] = mapped_column(ForeignKey("api_tokens.id"))
    via: Mapped[str] = mapped_column(String(10), comment="http | stdio | agent (our own chat agent, in process)")
    name: Mapped[str] = mapped_column(String(80), comment="Tool name, or resource URI template")
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), comment="ok | error | refused | rate_limited")
    error: Mapped[str | None] = mapped_column(String(300))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Phase 5: support tickets and the knowledge base
# ---------------------------------------------------------------------------


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = {
        "comment": "A question a person must look at: the AI couldn't answer, wasn't sure, got a thumbs down, or it "
        "is a login/payment problem. Support resolves it; a resolved academic answer can go into the knowledge base."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doubt_id: Mapped[int | None] = mapped_column(ForeignKey("doubts.id"), unique=True, comment="The chat message")
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), comment="Best guess, from the sources")
    reason: Mapped[str] = mapped_column(
        String(20), comment="no_answer | low_confidence | thumbs_down | support | student (opened by the student)"
    )
    category: Mapped[str] = mapped_column(String(20), comment="academic | login | payment")
    subject: Mapped[str] = mapped_column(Text, comment="The student's question or message")
    draft: Mapped[str | None] = mapped_column(Text, comment="What the AI answered, as a starting point for support")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True, comment="open | in_progress | resolved")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(Text, comment="The answer the student sees")
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    saved_to_kb: Mapped[bool] = mapped_column(Boolean, default=False)
    question_vec: Mapped[list | None] = mapped_column(JSON, comment="Embedding of the subject (similar tickets)")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class FaqEntry(Base):
    __tablename__ = "faq_entries"
    __table_args__ = {
        "comment": "Knowledge base: answers written by support (from resolved tickets). Retrieval searches them "
        "next to course material, so the AI uses a resolved answer the next time someone asks."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    question_vec: Mapped[list] = mapped_column(JSON, comment="Embedding of the question")
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    active: Mapped[bool] = mapped_column(Boolean, default=True, comment="Support can withdraw an entry")


# ---------------------------------------------------------------------------
# Phase 6: the SQL agent
# ---------------------------------------------------------------------------


class SqlQuery(Base):
    __tablename__ = "sql_queries"
    __table_args__ = {
        "comment": "Every question asked to the SQL agent: the SQL it wrote (each attempt), how it went, and the "
        "answer. The agent itself can't read this table."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    sql: Mapped[str | None] = mapped_column(Text, comment="The query that ran (the last attempt)")
    attempts: Mapped[list] = mapped_column(
        JSON, default=list, comment="[{sql, error, stage}] for every try, so self-corrections are visible"
    )
    status: Mapped[str] = mapped_column(
        String(20), comment="answered | no_rows | refused (not a data question, or asks to change data) | failed"
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, comment="More rows than SQL_AGENT_MAX_ROWS")
    answer: Mapped[str | None] = mapped_column(Text)
    chart: Mapped[dict | None] = mapped_column(JSON, comment="{type: bar | line | number, x, y} chosen by code")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


# ---------------------------------------------------------------------------
# Phase 7: guardrails and evaluation
# ---------------------------------------------------------------------------


class GuardrailEvent(Base):
    __tablename__ = "guardrail_events"
    __table_args__ = {
        "comment": "Guardrail log: a message refused before answering (prompt injection, off topic) or an answer "
        "flagged after it (bad citation, prompt leak, someone's email). Messages that pass are not logged."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    doubt_id: Mapped[int | None] = mapped_column(ForeignKey("doubts.id", ondelete="SET NULL"))
    surface: Mapped[str] = mapped_column(String(10), comment="chat | mcp")
    stage: Mapped[str] = mapped_column(String(10), comment="input (before answering) | output (after)")
    kind: Mapped[str] = mapped_column(
        String(20), comment="injection | off_topic | prompt_leak | email | invalid_citation | uncited"
    )
    action: Mapped[str] = mapped_column(String(10), comment="blocked (not answered) | flagged (answered, marked)")
    method: Mapped[str] = mapped_column(String(20), comment="rules | llm | code")
    text: Mapped[str] = mapped_column(Text, comment="The message (cut to 500 characters)")
    detail: Mapped[dict] = mapped_column(JSON, default=dict, comment="Rule that fired, LLM reason, citations...")


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = {
        "comment": "One run of the answer-quality eval (python -m app.evals.answers): scores per question and "
        "averages, with the settings it ran with, so two versions can be compared."
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="answers")
    label: Mapped[str | None] = mapped_column(String(80), comment="What changed, e.g. 'chunk 600' or a git commit")
    config: Mapped[dict] = mapped_column(JSON, default=dict, comment="Model, judge, chunking and retrieval settings")
    summary: Mapped[dict] = mapped_column(JSON, default=dict, comment="Average of each metric")
    items: Mapped[list] = mapped_column(JSON, default=list, comment="Scores per question")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
