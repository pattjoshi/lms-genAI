"""Phase 5: tickets, the knowledge base and grouping questions by meaning. No LLM, no database."""

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app.mcp_server import server, tokens
from app.models import Doubt, FaqEntry, Role, Ticket, User
from app.permissions import Resource
from app.rag import retriever
from app.rag.answer import confidence
from app.rag.retriever import RetrievalOptions, retrieve
from app.tickets import faq, insights, service, vectors

# --- vectors ---------------------------------------------------------------


def test_cosine():
    assert vectors.cosine([1, 0], [1, 0]) == pytest.approx(1)
    assert vectors.cosine([1, 0], [0, 1]) == pytest.approx(0)
    assert vectors.cosine([1, 1], [2, 2]) == pytest.approx(1)  # length doesn't matter
    assert vectors.cosine([0, 0], [1, 0]) == 0.0


def test_nearest_keeps_only_close_items_best_first():
    items = [("a", [1, 0]), ("b", [0.9, 0.1]), ("c", [0, 1]), ("no vector", None)]
    found = vectors.nearest([1, 0], items, min_sim=0.8, k=5)
    assert [x for x, _ in found] == ["a", "b"]
    assert vectors.nearest([1, 0], items, min_sim=0.8, k=1)[0][0] == "a"


def test_group_puts_paraphrases_together():
    items = [
        ("overfit 1", [1.0, 0.05, 0]),
        ("dropout", [0, 1.0, 0]),
        ("overfit 2", [0.95, 0.1, 0]),
        ("overfit 3", [0.9, 0, 0.1]),
        ("joins", [0, 0, 1.0]),
    ]
    groups = vectors.group(items, min_sim=0.9)
    assert [sorted(g.members) for g in groups] == [["overfit 1", "overfit 2", "overfit 3"], ["dropout"], ["joins"]]
    assert groups[0].total == pytest.approx([2.85, 0.15, 0.1])  # running sum of the members


# --- when a chat message becomes a ticket ----------------------------------


@pytest.mark.parametrize(
    ("intent", "status", "conf", "reason"),
    [
        ("doubt", "no_context", None, "no_answer"),
        (None, "no_context", None, "no_answer"),  # Phase 1 rows have no intent
        ("doubt", "answered", "low", "low_confidence"),
        ("doubt", "answered", "high", None),
        ("doubt", "error", None, None),
        ("support", "answered", None, "support"),
        ("learning_path", "answered", None, None),
        ("practice", "no_context", None, None),
    ],
)
def test_auto_reason(intent, status, conf, reason):
    assert service.auto_reason(Doubt(intent=intent, status=status, confidence=conf)) == reason


def test_category():
    assert service.category_for("How does dropout work?", "doubt") == "academic"
    assert service.category_for("I can't log in, OTP expired", "support") == "login"
    assert service.category_for("My payment failed but money was debited", "support") == "payment"


# --- P8: support sees the student only through an open ticket ---------------


def user(role: Role, uid: int = 1) -> User:
    return User(id=uid, full_name="x", role=role, is_active=True)


@pytest.mark.parametrize(("status", "visible"), [("open", True), ("in_progress", True), ("resolved", False)])
def test_support_sees_records_only_while_the_ticket_is_open(status, visible):
    t = Ticket(status=status)
    assert service.can_see_records(user(Role.support), t, Resource.STUDENT_RECORDS) is visible
    assert service.can_see_records(user(Role.support), t, Resource.PAYMENTS) is visible
    assert service.can_see_records(user(Role.admin), t, Resource.PAYMENTS) is True
    assert service.can_see_records(user(Role.teacher), t, Resource.PAYMENTS) is False


# --- resolving ---------------------------------------------------------------


class FakeSession:
    def __init__(self, ticket: Ticket):
        self.ticket, self.added = ticket, []

    async def get(self, model, id_):
        return self.ticket if model is Ticket else None

    def add(self, obj):
        self.added.append(obj)


async def test_resolve_saves_a_course_answer_to_the_knowledge_base():
    t = Ticket(id=5, status="open", category="academic", course_id=3, subject="What is dropout?", question_vec=[1, 0])
    s = FakeSession(t)
    await service.resolve(s, user(Role.support, 2), 5, "Dropout switches off random neurons.", save_to_kb=True)
    assert t.status == "resolved" and t.saved_to_kb and t.resolved_by == 2
    [entry] = s.added
    assert isinstance(entry, FaqEntry)
    assert (entry.course_id, entry.question, entry.question_vec, entry.ticket_id) == (3, "What is dropout?", [1, 0], 5)


async def test_resolve_without_kb_saves_nothing_else():
    t = Ticket(id=5, status="in_progress", category="academic", course_id=3, subject="q", question_vec=[1, 0])
    s = FakeSession(t)
    await service.resolve(s, user(Role.support), 5, "Only for you.", save_to_kb=False)
    assert t.status == "resolved" and not t.saved_to_kb and s.added == []


@pytest.mark.parametrize(
    ("ticket", "message"),
    [
        (Ticket(status="open", category="payment", course_id=3), "Only course questions"),
        (Ticket(status="open", category="academic", course_id=None), "Pick the course"),
        (Ticket(status="resolved", category="academic", course_id=3), "already resolved"),
    ],
)
async def test_resolve_refuses(ticket, message):
    with pytest.raises(service.TicketError, match=message):
        await service.resolve(FakeSession(ticket), user(Role.support), 1, "answer", save_to_kb=True)


# --- the knowledge base inside retrieval -------------------------------------


@pytest.fixture
def search_stubs(monkeypatch):
    async def readable(_s, _u):
        return [1]

    async def embed(_s, texts, **_kw):
        from app.llm.service import EmbeddingResult

        return EmbeddingResult(vectors=[[1.0, 0.0] for _ in texts], tokens=3, cost_usd=0.0)

    async def search(_vec, _kw, _courses, _limit, _module=None):
        return [], []  # the course material has nothing

    monkeypatch.setattr(retriever, "readable_course_ids", readable)
    monkeypatch.setattr(retriever, "embed_texts", embed)
    monkeypatch.setattr(retriever.vectorstore, "search", search)


async def test_a_verified_answer_is_used_when_the_material_has_nothing(search_stubs, monkeypatch):
    seen = {}

    async def faq_search(_s, vec, course_ids):
        seen["vec"], seen["courses"] = vec, course_ids
        entry = FaqEntry(id=7, question="What is dropout?", answer="It switches off neurons.")
        return [faq.as_source(entry, "DL301", 0.93)]

    monkeypatch.setattr(retriever, "faq_search", faq_search)
    r = await retrieve(None, None, "what is dropout", options=RetrievalOptions(rewrite=False, corrective=False))
    assert seen == {"vec": [1.0, 0.0], "courses": [1]}  # same query vector, same course scope
    assert r.has_context and r.faq_hits == 1
    assert r.sources[0]["file_name"] == faq.LABEL and r.sources[0]["faq_id"] == 7
    assert confidence(r.relevance()) == "high"


async def test_baseline_skips_the_knowledge_base(search_stubs, monkeypatch):
    async def faq_search(*_a):
        raise AssertionError("must not be called")

    monkeypatch.setattr(retriever, "faq_search", faq_search)
    r = await retrieve(None, None, "what is dropout", options=RetrievalOptions.baseline())
    assert not r.has_context


async def test_a_broken_knowledge_base_never_breaks_search(search_stubs, monkeypatch):
    async def faq_search(*_a):
        raise RuntimeError("db down")

    monkeypatch.setattr(retriever, "faq_search", faq_search)
    r = await retrieve(None, None, "what is dropout", options=RetrievalOptions(rewrite=False, corrective=False))
    assert not r.has_context and "Knowledge base skipped" in r.warnings[0]


# --- teacher insights ----------------------------------------------------------


def test_insight_groups():
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    d = [
        Doubt(id=1, student_id=10, question="How do I stop overfitting?", status="answered", created_at=now,
              sources=[{"course_code": "DL301"}]),
        Doubt(id=2, student_id=11, question="model memorises training data", status="no_context", created_at=now,
              sources=[{"course_code": "DL301"}]),
        Doubt(id=3, student_id=10, question="How do I stop overfitting?", status="answered", created_at=now,
              sources=[{"course_code": "DL301"}], feedback=-1),
    ]  # fmt: skip
    vecs = {1: [1, 0], 2: [0.95, 0.1], 3: [1, 0]}
    groups = vectors.group([(x, vecs[x.id]) for x in d], 0.9)
    [g] = insights.summarise(groups, vecs, {2: "open", 3: "in knowledge base"})
    assert g["count"] == 3 and g["students"] == 2 and g["course_code"] == "DL301"
    assert g["label"] == "How do I stop overfitting?" and g["examples"] == [d[0].question, d[1].question]
    assert (g["unanswered"], g["thumbs_down"], g["ticket_status"]) == (1, 1, "in knowledge base")
    assert [insights.is_gap(x) for x in d] == [False, True, True]


# --- MCP: create_ticket asks first ----------------------------------------------


@pytest.fixture
def as_user(monkeypatch):
    rows = []

    async def fake_audit(identity, name, arguments, status, error, ms):
        rows.append((name, status))

    monkeypatch.setattr(server, "_audit", fake_audit)

    class Session:
        def __init__(self, u):
            self.u = u

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, model, id_):
            return self.u

    async def no_budget(*_a):
        return None

    monkeypatch.setattr(server, "ensure_budget_available", no_budget)

    def set_user(u: User):
        monkeypatch.setattr(server, "SessionLocal", lambda: Session(u))
        return server.local_identity.set(tokens.Identity(user=u, via="agent"))

    yield set_user, rows


async def test_create_ticket_without_confirm_only_previews(as_user, monkeypatch):
    set_user, rows = as_user

    async def must_not_create(*_a, **_kw):
        raise AssertionError("no ticket without confirm")

    monkeypatch.setattr(server.tickets_svc, "open_by_student", must_not_create)
    token = set_user(user(Role.student, 10))
    try:
        out = await server.create_ticket("My certificate never arrived")
    finally:
        server.local_identity.reset(token)
    assert out["created"] is False and "confirm=true" in out["message"]
    assert rows == [("create_ticket", "ok")]


async def test_create_ticket_is_for_students(as_user):
    set_user, rows = as_user
    token = set_user(user(Role.teacher, 6))
    try:
        with pytest.raises(ToolError, match="Only students"):
            await server.create_ticket("Please help", confirm=True)
    finally:
        server.local_identity.reset(token)
    assert rows == [("create_ticket", "refused")]
