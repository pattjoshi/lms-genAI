"""Phase 7: the numbers on the admin's "AI quality & cost" page, its permission, and trace links. No DB, no LLM."""

from datetime import date

import pytest

from app.llm import tracing
from app.llm.stats import MessageRow, UsageRow, chat_summary, guardrail_summary, percentile, usage_summary
from app.models import Role, User
from app.permissions import PermissionDenied
from app.routers.quality import require_ai_usage

D1, D2 = date(2026, 10, 16), date(2026, 10, 17)


def test_percentile_nearest_rank():
    values = list(range(1, 101))  # 1..100
    assert percentile(values, 50) == 50 and percentile(values, 95) == 95 and percentile(values, 100) == 100
    assert percentile([300, 100, 200], 50) == 200
    assert percentile([5000], 95) == 5000
    assert percentile([], 95) is None


def usage(day, feature, cost, ms, role="student", status="success", attempts=1, code=None):
    return UsageRow(day, feature, "gpt-4o-mini", role, 1000, 100, cost, ms, attempts, status, code)


def test_usage_summary_cost_and_latency():
    rows = [
        usage(D1, "rag_answer", 0.0010, 1200),
        usage(D1, "rag_answer", 0.0020, 2400, attempts=2),
        usage(D2, "route_embed", 0.0000, 90, role=None),
        usage(D2, "rag_answer", 0.0, 30000, status="error", code="timeout"),
    ]
    s = usage_summary(rows, [D1, D2])
    assert s["calls"] == 4 and s["errors"] == 1 and s["retried"] == 1 and s["cost_usd"] == 0.003
    assert s["projected_month_usd"] == pytest.approx(0.003 / 2 * 30)
    assert s["per_day"] == [
        {"day": "2026-10-16", "cost_usd": 0.003, "calls": 2, "errors": 0, "p95_ms": 2400},
        {"day": "2026-10-17", "cost_usd": 0.0, "calls": 2, "errors": 1, "p95_ms": 30000},
    ]
    rag = s["by_feature"][0]
    assert rag["feature"] == "rag_answer" and rag["calls"] == 3 and rag["errors"] == 1
    assert rag["p50"] == 1200 and rag["p95"] == 2400  # a failed call's time is not an answer's latency
    assert {r["role"] for r in s["by_role"]} == {"student", "system"}
    assert s["errors_by_code"] == {"timeout": 1}


def msg(intent="doubt", status="answered", conf="high", feedback=None, ms=2000, ttft=400, checks=None, day=D1):
    return MessageRow(day, intent, status, conf, feedback, ms, ttft, 0.0005, checks)


def test_chat_summary_quality_and_latency():
    ok = {"output": {"invalid_citations": [], "coverage": 1.0, "flags": []}}
    bad = {"output": {"invalid_citations": [7], "coverage": 0.5, "flags": ["invalid_citation"]}}
    rows = [
        msg(checks=ok, feedback=1),
        msg(checks=bad, conf="low", feedback=-1, ms=6000, ttft=900),
        msg(status="no_context", conf=None, ttft=None),
        msg(intent="guardrail", status="blocked", conf=None, ttft=None, ms=300),
        msg(intent="practice", conf=None, ttft=None, day=D2),
    ]
    s = chat_summary(rows, [D1, D2])
    q = s["quality"]
    assert q["course_questions"] == 3 and q["answered"] == 2 and q["no_answer_rate"] == 0.333
    assert q["low_confidence_rate"] == 0.5 and q["blocked"] == 1
    assert q["thumbs_up"] == 1 and q["thumbs_down"] == 1 and q["satisfaction"] == 0.5
    assert q["valid_citations_rate"] == 0.5 and q["avg_citation_coverage"] == 0.75 and q["flagged_answers"] == 1
    assert s["first_token"] == {"p50": 400, "p95": 900, "max": 900}
    assert s["by_intent"]["doubt"] == 3 and s["per_day"][1]["messages"] == 1


def test_guardrail_summary():
    s = guardrail_summary([("input", "off_topic", "blocked"), ("input", "injection", "blocked"),
                           ("output", "uncited", "flagged"), ("input", "off_topic", "blocked")])  # fmt: skip
    assert s == {"blocked": 3, "flagged": 1,
                 "by_kind": {"input:off_topic": 2, "input:injection": 1, "output:uncited": 1}}  # fmt: skip


@pytest.mark.parametrize(("role", "allowed"), [(Role.admin, True), (Role.teacher, False), (Role.student, False),
                                               (Role.support, False)])  # fmt: skip
async def test_only_the_permission_matrix_lets_admins_in(role, allowed):
    user = User(id=1, full_name="x", role=role)
    if allowed:
        assert await require_ai_usage(user) is user
    else:
        with pytest.raises(PermissionDenied):
            await require_ai_usage(user)


def test_trace_links_need_langfuse(monkeypatch):
    monkeypatch.setattr(tracing, "_client", None)
    assert tracing.trace_url("abc") is None and tracing.current_trace_id() is None
    tracing.score("abc", "faithfulness", 1.0)  # a no-op, never an error

    class FakeLangfuse:
        def get_trace_url(self, trace_id):
            return f"https://us.cloud.langfuse.com/project/p1/traces/{trace_id}"

    monkeypatch.setattr(tracing, "_client", FakeLangfuse())
    monkeypatch.setattr(tracing, "_trace_url_prefix", None)
    assert tracing.trace_url("abc") == "https://us.cloud.langfuse.com/project/p1/traces/abc"
    assert tracing.trace_url(None) is None
