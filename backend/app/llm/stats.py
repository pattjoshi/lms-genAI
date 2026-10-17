"""Numbers for the admin's "AI quality & cost" dashboard (Phase 7: A4 cost, A5 latency, A6 quality, A9 guardrails).

Everything is computed from our own tables, not from Langfuse: `llm_usage` (one row per LLM call, since
Phase 0), `doubts` (one row per chat message) and `guardrail_events`. Langfuse holds the detail of each
request (prompts, spans); the dashboard links to it by trace id instead of copying it.

The functions here are pure (rows in, dict out), so they are tested without a database. The router only
fetches the rows of the chosen window. Percentiles are computed in Python: a demo LMS makes a few thousand
calls a week, and the nearest-rank method is easy to check by hand. At millions of rows, use Postgres'
`percentile_cont` or Langfuse's own dashboards.

Why p50 and p95 and not the average: latency has a long tail. One 20 s retry pulls the average up while the
typical request didn't change; p95 says "1 in 20 requests is slower than this", which is what users feel.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date


def percentile(values: list[float], p: float) -> int | None:
    """Nearest-rank percentile: the smallest value with at least p% of the values at or below it."""
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    rank = max(1, math.ceil(p / 100 * len(data)))
    return int(data[rank - 1])


def _latency(values: list[int]) -> dict:
    return {"p50": percentile(values, 50), "p95": percentile(values, 95), "max": max(values) if values else None}


@dataclass
class UsageRow:
    day: date  # in APP_TIMEZONE
    feature: str
    model: str
    role: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    attempts: int
    status: str
    error_code: str | None


def usage_summary(rows: list[UsageRow], days: list[date]) -> dict:
    """Cost (A4) and LLM-call latency (A5), in total, per day, per feature, per role and per model."""
    per_day = {d: {"day": d.isoformat(), "cost_usd": 0.0, "calls": 0, "errors": 0, "_lat": []} for d in days}
    groups: dict[str, dict] = {"feature": {}, "role": {}, "model": {}}
    errors: dict[str, int] = defaultdict(int)
    for r in rows:
        day = per_day.get(r.day)
        if day is not None:
            day["cost_usd"] += r.cost_usd
            day["calls"] += 1
            day["errors"] += r.status == "error"
            day["_lat"].append(r.latency_ms)
        for kind, key in (("feature", r.feature), ("role", r.role or "system"), ("model", r.model)):
            g = groups[kind].setdefault(
                key,
                {kind: key, "calls": 0, "errors": 0, "retried": 0, "cost_usd": 0.0, "input_tokens": 0,
                 "output_tokens": 0, "_lat": []},
            )  # fmt: skip
            g["calls"] += 1
            g["errors"] += r.status == "error"
            g["retried"] += r.attempts > 1
            g["cost_usd"] += r.cost_usd
            g["input_tokens"] += r.input_tokens
            g["output_tokens"] += r.output_tokens
            if r.status == "success":
                g["_lat"].append(r.latency_ms)
        if r.status == "error":
            errors[r.error_code or "unknown"] += 1

    def finish(g: dict) -> dict:
        lat = g.pop("_lat")
        g["cost_usd"] = round(g["cost_usd"], 6)
        g.update(_latency(lat))
        return g

    daily = []
    for d in days:
        row = per_day[d]
        lat = row.pop("_lat")
        daily.append({**row, "cost_usd": round(row["cost_usd"], 6), "p95_ms": percentile(lat, 95)})
    total_cost = sum(r.cost_usd for r in rows)
    by = {
        kind: sorted((finish(g) for g in vals.values()), key=lambda g: -g["cost_usd"]) for kind, vals in groups.items()
    }
    return {
        "calls": len(rows),
        "errors": sum(1 for r in rows if r.status == "error"),
        "retried": sum(1 for r in rows if r.attempts > 1),
        "cost_usd": round(total_cost, 6),
        "input_tokens": sum(r.input_tokens for r in rows),
        "output_tokens": sum(r.output_tokens for r in rows),
        # What a month at this window's pace would cost: the number to compare with the OpenAI limit.
        "projected_month_usd": round(total_cost / max(len(days), 1) * 30, 4),
        "per_day": daily,
        "by_feature": by["feature"],
        "by_role": by["role"],
        "by_model": by["model"],
        "errors_by_code": dict(sorted(errors.items(), key=lambda kv: -kv[1])),
    }


@dataclass
class MessageRow:
    day: date
    intent: str | None
    status: str
    confidence: str | None
    feedback: int | None
    latency_ms: int
    first_token_ms: int | None
    cost_usd: float
    checks: dict | None


def chat_summary(rows: list[MessageRow], days: list[date]) -> dict:
    """End-to-end chat latency (A5) and live answer quality (A6). "Course answers" = messages that went to RAG."""
    course = [r for r in rows if r.intent in (None, "doubt")]
    answered = [r for r in course if r.status == "answered"]
    outputs = [(r.checks or {}).get("output") for r in answered]
    outputs = [o for o in outputs if o]
    coverage = [o["coverage"] for o in outputs if o.get("coverage") is not None]
    rated = [r for r in rows if r.feedback in (1, -1)]
    per_day = []
    for d in days:
        today = [r for r in rows if r.day == d]
        per_day.append(
            {
                "day": d.isoformat(),
                "messages": len(today),
                "p50_ms": percentile([r.latency_ms for r in today], 50),
                "p95_ms": percentile([r.latency_ms for r in today], 95),
            }
        )

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 3) if whole else None

    return {
        "messages": len(rows),
        "latency": _latency([r.latency_ms for r in rows if r.status != "error"]),
        "first_token": _latency([r.first_token_ms for r in answered if r.first_token_ms]),
        "cost_per_message_usd": round(sum(r.cost_usd for r in rows) / len(rows), 6) if rows else None,
        "per_day": per_day,
        "by_intent": dict(sorted(_count(r.intent or "doubt" for r in rows).items(), key=lambda kv: -kv[1])),
        "quality": {
            "course_questions": len(course),
            "answered": len(answered),
            "no_answer_rate": share(sum(r.status == "no_context" for r in course), len(course)),
            "low_confidence_rate": share(sum(r.confidence == "low" for r in answered), len(answered)),
            "blocked": sum(r.status == "blocked" for r in rows),
            "errors": sum(r.status == "error" for r in rows),
            "thumbs_up": sum(r.feedback == 1 for r in rated),
            "thumbs_down": sum(r.feedback == -1 for r in rated),
            "satisfaction": share(sum(r.feedback == 1 for r in rated), len(rated)),
            # Groundedness, the live way: cheap code checks on every answer (app/guardrails/output.py)
            "checked_answers": len(outputs),
            "valid_citations_rate": share(sum(not o.get("invalid_citations") for o in outputs), len(outputs)),
            "avg_citation_coverage": round(sum(coverage) / len(coverage), 3) if coverage else None,
            "flagged_answers": sum(1 for o in outputs if o.get("flags")),
        },
    }


def _count(values) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for v in values:
        out[v] += 1
    return dict(out)


def guardrail_summary(events: list[tuple[str, str, str]]) -> dict:
    """events = [(stage, kind, action)] -> counts per kind, for the guardrail cards."""
    by_kind = _count(f"{stage}:{kind}" for stage, kind, _ in events)
    return {
        "blocked": sum(1 for _, _, action in events if action == "blocked"),
        "flagged": sum(1 for _, _, action in events if action == "flagged"),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
    }
