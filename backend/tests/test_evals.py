"""Phase 7: the answer-quality eval: metrics in code, the judge (faked), comparison of two runs, the eval set."""

import re

import pytest
import yaml

from app.config import REPO_ROOT, get_settings
from app.evals import answers as ev
from app.guardrails.input import Verdict
from app.llm.service import LLMResult
from app.models import Role, User
from app.prompts.rag_answer import NO_ANSWER
from app.rag.retriever import Retrieval

ITEM = {
    "id": "Q11",
    "question": "How are gradients computed?",
    "course": "DL301",
    "module": 2,
    "topic": "Backpropagation",
}
RIGHT = {"file_name": "DL301_M2_Training.docx", "topic": "Backpropagation", "used": True, "text": "Backprop uses..."}
WRONG = {"file_name": "DL301_M2_Training.docx", "topic": "Optimizers", "used": True, "text": "Adam is..."}


def test_context_precision_rewards_the_right_excerpt_first():
    assert ev.context_precision([RIGHT, WRONG, WRONG], ITEM) == 1.0
    assert ev.context_precision([WRONG, WRONG, RIGHT], ITEM) == 0.333
    assert ev.context_precision([WRONG, RIGHT, RIGHT], ITEM) == pytest.approx((1 / 2 + 2 / 3) / 2, abs=0.001)
    assert ev.context_precision([WRONG], ITEM) == 0.0
    assert ev.context_recall([WRONG, RIGHT], ITEM) == 1.0 and ev.context_recall([WRONG], ITEM) == 0.0
    faq = {"faq": True, "course_code": "DL301", "used": True}
    assert ev.context_recall([faq], ITEM) == 1.0  # a verified support answer for the course counts


def test_the_judges_evidence_is_checked_in_code():
    excerpts = "[1] (DL301)\nIn the backward pass, the algorithm starts at the loss and moves backwards."
    claims = [
        ev.Claim(claim="It starts at the loss", supported=True, evidence="the algorithm starts at the loss"),
        ev.Claim(claim="Hinton invented it", supported=True, evidence="Hinton invented backpropagation in 2012"),
        ev.Claim(claim="It is fast", supported=False, evidence=""),
    ]
    score, mismatch, out = ev.faithfulness_score(claims, excerpts)
    assert score == 0.333 and mismatch == 1  # the made-up quote doesn't count as support
    assert [c["supported"] for c in out] == [True, False, False]
    assert ev.faithfulness_score([], excerpts)[0] is None  # "not in the material" makes no claims
    assert not ev.evidence_found("the loss", excerpts)  # too short to prove anything


def test_judge_checks():
    def grade(f, r):
        return ev.Grade(f, [], r, True, "", 0, 0.0)

    assert ev.judge_check_passed("unfaithful", grade(0.0, 1.0))
    assert not ev.judge_check_passed("unfaithful", grade(0.9, 1.0))
    assert ev.judge_check_passed("off_question", grade(1.0, 0.25))
    assert not ev.judge_check_passed("off_question", grade(1.0, 0.75))


def admin() -> User:
    return User(id=1, full_name="Neha Kapoor", email="neha@lmsdemo.in", role=Role.admin)


async def test_judge_uses_the_judge_model_and_scales_relevance(monkeypatch):
    calls = []

    async def chat_structured(_s, *, messages, schema, feature, user, max_tokens=None, model=None):
        calls.append((schema.__name__, feature, model, messages[1].content))
        if schema is ev.FaithfulnessGrade:
            claim = ev.Claim(claim="Adam uses 0.001", supported=True, evidence="a learning rate of 0.001, beta1 of 0.9")
            return schema(claims=[claim]), LLMResult("", "judge", 300, 50, 0.0001, 5, 1)
        return schema(relevance=4, correct=True, reason="ok"), LLMResult("", "judge", 200, 20, 0.0001, 5, 1)

    monkeypatch.setattr(ev, "chat_structured", chat_structured)
    monkeypatch.setattr(get_settings(), "eval_judge_model", "gpt-4o")
    excerpts = "[1] Its usual defaults are a learning rate of 0.001, beta1 of 0.9 and beta2 of 0.999."
    g = await ev.judge(None, admin(), "Adam defaults?", "lr 0.001", excerpts, "0.001 [1]")
    assert g.faithfulness == 1.0 and g.relevance == 0.75 and g.correct and g.cost_usd == pytest.approx(0.0002)
    assert [(c[0], c[1], c[2]) for c in calls] == [
        ("FaithfulnessGrade", "eval_judge", "gpt-4o"),
        ("RelevanceGrade", "eval_judge", "gpt-4o"),
    ]
    assert "<reference>\nlr 0.001\n</reference>" in calls[1][3]  # graded against the teacher's reference


@pytest.fixture
def pipeline(monkeypatch):
    """Fake guardrail, retrieval, answer and judge for run_item."""

    class P:
        verdict = Verdict(True, None, "embedding")
        sources: list = []
        answer = "Backpropagation applies the chain rule backwards [1]."

    async def check_input(_s, _u, _t):
        return P.verdict

    async def retrieve(_s, _u, question, **_kw):
        return Retrieval(question=question, query=question, sources=P.sources)

    async def chat(_s, **_kw):
        return LLMResult(P.answer, "test", 500, 60, 0.0002, 5, 1)

    async def judge(*_a):
        return ev.Grade(0.5, [], 1.0, False, "contradicts the reference", 0, 0.0003)

    monkeypatch.setattr(ev, "check_input", check_input)
    monkeypatch.setattr(ev, "retrieve", retrieve)
    monkeypatch.setattr(ev, "chat", chat)
    monkeypatch.setattr(ev, "judge", judge)
    return P


async def test_run_item_grades_an_answer(pipeline):
    pipeline.sources = [RIGHT, WRONG, {**WRONG, "used": False}]
    row, excerpts = await ev.run_item(None, admin(), ITEM)
    assert row["answered"] and row["guard"] is None
    assert row["context_precision"] == 1.0 and row["context_recall"] == 1.0
    assert row["faithfulness"] == 0.5 and row["relevance"] == 1.0 and row["correctness"] == 0.0
    assert row["cost_usd"] == pytest.approx(0.0005)
    assert excerpts.startswith("[1]") and "[3]" not in excerpts  # only the used excerpts reach the LLM


async def test_run_item_no_context_is_not_answered_and_not_judged(pipeline):
    pipeline.sources = [{**WRONG, "used": False}]
    row, _ = await ev.run_item(None, admin(), ITEM)
    assert not row["answered"] and row["answer"] == NO_ANSWER
    assert row["context_recall"] == 0.0 and "faithfulness" not in row


async def test_run_item_refused_by_the_guardrail(pipeline):
    pipeline.verdict = Verdict(False, "off_topic", "llm", "cricket")
    row, _ = await ev.run_item(None, admin(), {"id": "G01", "question": "Cricket?", "expect": "off_topic"})
    assert row["guard"] == "off_topic" and row["guard_method"] == "llm" and not row["answered"]


def rows():
    return [
        {"id": "Q1", "expect": "answer", "answered": True, "context_precision": 1.0, "context_recall": 1.0,
         "faithfulness": 1.0, "relevance": 1.0, "correctness": 1.0, "ms": 1000, "cost_usd": 0.001},
        {"id": "Q2", "expect": "answer", "answered": False, "context_precision": 0.0, "context_recall": 0.0,
         "ms": 500, "cost_usd": 0.0},
        {"id": "N1", "expect": "no_answer", "answered": False, "ms": 400, "cost_usd": 0.0},
        {"id": "G1", "expect": "off_topic", "answered": False, "guard": "off_topic", "ms": 100, "cost_usd": 0.0},
        {"id": "I1", "expect": "injection", "answered": True, "guard": None, "ms": 900, "cost_usd": 0.001},
    ]  # fmt: skip


def test_summary():
    s = ev.summarize(rows(), [{"passed": True, "cost_usd": 0.001}, {"passed": False, "cost_usd": 0.001}])
    assert s["context_recall"] == 0.5 and s["faithfulness"] == 1.0 and s["answer_rate"] == 0.5
    assert s["no_answer_ok"] == pytest.approx(0.667, abs=0.001)  # the injection was answered
    assert s["guard_blocked"] == 0.5 and s["over_blocked"] == 0 and s["judge_checks"] == 0.5
    assert s["avg_ms"] == 580 and s["cost_usd"] == 0.004 and s["questions"] == 5


def test_compare_marks_better_worse_and_same():
    before = {"faithfulness": 0.80, "context_recall": 0.90, "relevance": 0.85, "avg_ms": 2000, "over_blocked": 0,
              "cost_usd": 0.030}  # fmt: skip
    now = {"faithfulness": 0.90, "context_recall": 0.80, "relevance": 0.86, "avg_ms": 3000, "over_blocked": 1,
           "cost_usd": 0.020}  # fmt: skip
    verdicts = {r["metric"]: r["verdict"] for r in ev.compare(now, before, 0.02)}
    assert verdicts["faithfulness"] == "better" and verdicts["context_recall"] == "worse"
    assert verdicts["relevance"] == "same"  # +0.01 is noise, not a change
    assert verdicts["avg_ms"] == "worse" and verdicts["over_blocked"] == "worse"  # lower is better for these
    assert verdicts["cost_usd"] == "better" and verdicts["correctness"] == "-"  # missing in both runs


def test_regressions_name_the_questions_to_read():
    before = rows()
    now = [dict(r) for r in rows()]
    now[0]["faithfulness"] = 0.5
    now[2]["guard"] = "off_topic"
    now[3]["guard"] = None
    lines = ev.regressions(now, before)
    assert any(line.startswith("Q1: faithfulness 1.00 -> 0.50") for line in lines)
    assert any(line.startswith("N1: now wrongly refused") for line in lines)
    assert any(line.startswith("G1: no longer refused") for line in lines)


def test_overrides_are_validated_like_the_env_file(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rag_rerank", True)
    monkeypatch.setattr(s, "rag_top_k", 5)
    assert ev.apply_overrides(["RAG_RERANK=false", "rag_top_k=3"]) == {"RAG_RERANK": "false", "RAG_TOP_K": "3"}
    assert s.rag_rerank is False and s.rag_top_k == 3
    with pytest.raises(SystemExit):
        ev.apply_overrides(["NOT_A_SETTING=1"])


# --- the eval set itself ---------------------------------------------------------


def test_the_eval_set_is_well_formed():
    data = yaml.safe_load(ev.QUESTIONS.read_text(encoding="utf-8"))
    questions, checks = data["questions"], data["judge_checks"]
    ids = [q["id"] for q in questions] + [c["id"] for c in checks]
    assert len(ids) == len(set(ids))
    kinds = {q.get("expect", "answer") for q in questions}
    assert kinds == {"answer", "no_answer", "off_topic", "injection"}
    for q in questions:
        if q.get("expect", "answer") != "answer":
            continue
        assert q["reference"].strip(), q["id"]
        source = (REPO_ROOT / "data" / "course_source" / q["course"] / f"m{q['module']}.md").read_text("utf-8")
        assert f"## {q['topic']}\n" in source, f"{q['id']}: topic {q['topic']!r} is not in {q['course']} m{q['module']}"
    by_id = {q["id"]: q for q in questions}
    for c in checks:
        assert by_id[c["of"]].get("expect", "answer") == "answer" and c["expect"] in ("unfaithful", "off_question")
        assert re.search(r"\[\d\]", c["answer"])  # planted answers look like real ones, citations included
