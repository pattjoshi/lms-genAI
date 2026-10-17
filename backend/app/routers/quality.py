"""Admin: "AI quality & cost" (Phase 7). Cost (A4), latency (A5), quality (A6), trace links (A7), eval runs and
their comparison (A8) and the guardrail log (A9). Admin only: the permission matrix's "AI usage dashboard" row.

The numbers come from llm_usage, doubts, guardrail_events and eval_runs (app/llm/stats.py does the maths).
Evals are run from the command line (`python -m app.evals.answers`), not from here: a run costs money and
takes minutes, which is a deliberate action, not a page load.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.auth import CurrentUser, SessionDep
from app.config import get_settings
from app.evals.answers import METRICS, compare
from app.llm.budget import spent_today_usd, start_of_today
from app.llm.stats import MessageRow, UsageRow, chat_summary, guardrail_summary, usage_summary
from app.llm.tracing import trace_url, tracing_enabled
from app.models import Doubt, EvalRun, GuardrailEvent, LLMUsage, User
from app.permissions import PermissionDenied, Resource, Scope, scope_for


async def require_ai_usage(user: CurrentUser) -> User:
    """The permission matrix's "AI usage dashboard" row decides, not a role list written here."""
    if scope_for(user.role, Resource.AI_USAGE) == Scope.NONE:
        raise PermissionDenied("The AI quality and cost dashboard is only for admins.")
    return user


router = APIRouter(prefix="/quality", tags=["quality"], dependencies=[Depends(require_ai_usage)])

MAX_ROWS = 50_000  # a safety cap for the window's rows


def _window(days: int) -> tuple[datetime, list, ZoneInfo]:
    s = get_settings()
    tz = ZoneInfo(s.app_timezone)
    today = start_of_today(s)
    since = today - timedelta(days=days - 1)
    return since, [(since + timedelta(days=i)).date() for i in range(days)], tz


@router.get("/dashboard")
async def dashboard(session: SessionDep, days: int = Query(7, ge=1, le=90)):
    s = get_settings()
    since, day_list, tz = _window(days)

    usage = (
        await session.execute(
            select(LLMUsage, User.role)
            .outerjoin(User, User.id == LLMUsage.user_id)
            .where(LLMUsage.created_at >= since)
            .order_by(LLMUsage.id.desc())
            .limit(MAX_ROWS)
        )
    ).all()
    usage_rows = [
        UsageRow(
            day=u.created_at.astimezone(tz).date(),
            feature=u.feature,
            model=u.model,
            role=role.value if role else None,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cost_usd=u.cost_usd,
            latency_ms=u.latency_ms,
            attempts=u.attempts,
            status=u.status,
            error_code=u.error_code,
        )
        for u, role in usage
    ]

    doubts = (
        await session.scalars(select(Doubt).where(Doubt.created_at >= since).order_by(Doubt.id.desc()).limit(MAX_ROWS))
    ).all()
    message_rows = [
        MessageRow(
            day=d.created_at.astimezone(tz).date(),
            intent=d.intent,
            status=d.status,
            confidence=d.confidence,
            feedback=d.feedback,
            latency_ms=d.latency_ms,
            first_token_ms=d.first_token_ms,
            cost_usd=d.cost_usd,
            checks=d.checks,
        )
        for d in doubts
    ]

    events = (
        await session.execute(
            select(GuardrailEvent.stage, GuardrailEvent.kind, GuardrailEvent.action).where(
                GuardrailEvent.created_at >= since
            )
        )
    ).all()

    runs = (
        await session.scalars(select(EvalRun).where(EvalRun.kind == "answers").order_by(EvalRun.id.desc()).limit(10))
    ).all()

    return {
        "days": days,
        "since": since.isoformat(),
        "budget": {
            "spent_today_usd": round(await spent_today_usd(session, s), 6),
            "daily_budget_usd": s.daily_budget_usd,
        },
        "usage": usage_summary(usage_rows, day_list),
        "chat": chat_summary(message_rows, day_list),
        "guardrails": guardrail_summary([tuple(e) for e in events]),
        "evals": [_run_out(r) for r in runs],
        "langfuse": {"enabled": tracing_enabled(), "base_url": s.langfuse_base_url if tracing_enabled() else None},
    }


def _run_out(r: EvalRun) -> dict:
    return {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "label": r.label,
        "config": r.config,
        "summary": r.summary,
        "cost_usd": r.cost_usd,
    }


@router.get("/evals")
async def evals(session: SessionDep, run_id: int | None = None, baseline_id: int | None = None):
    """A8: one run's scores per question, compared with another run (by default: the latest vs the one before)."""
    query = select(EvalRun).where(EvalRun.kind == "answers").order_by(EvalRun.id.desc())
    if run_id:
        query = query.where(EvalRun.id <= run_id)
    runs = (await session.scalars(query.limit(2))).all()
    if not runs:
        return {"run": None, "baseline": None, "compare": [], "metrics": {k: v[0] for k, v in METRICS.items()}}
    run = runs[0]
    baseline = await session.get(EvalRun, baseline_id) if baseline_id else (runs[1] if len(runs) > 1 else None)
    rows = compare(run.summary, baseline.summary, get_settings().eval_better_margin) if baseline else []
    items = [i for i in run.items if not i.get("judge_check")]
    for i in items:
        i["trace_url"] = trace_url(i.get("trace_id"))
    return {
        "run": {**_run_out(run), "items": items, "judge_checks": [i for i in run.items if i.get("judge_check")]},
        "baseline": _run_out(baseline) if baseline else None,
        "compare": rows,
    }


@router.get("/guardrails")
async def guardrails(session: SessionDep, limit: int = Query(50, ge=1, le=200), kind: str | None = None):
    """A9: the guardrail log, newest first."""
    query = (
        select(GuardrailEvent, User.full_name, User.role)
        .outerjoin(User, User.id == GuardrailEvent.user_id)
        .order_by(GuardrailEvent.id.desc())
        .limit(limit)
    )
    if kind:
        query = query.where(GuardrailEvent.kind == kind)
    rows = (await session.execute(query)).all()
    return [
        {
            "id": e.id,
            "at": e.created_at.isoformat() if e.created_at else None,
            "user": name,
            "role": role.value if role else None,
            "surface": e.surface,
            "stage": e.stage,
            "kind": e.kind,
            "action": e.action,
            "method": e.method,
            "text": e.text,
            "detail": e.detail,
            "doubt_id": e.doubt_id,
        }
        for e, name, role in rows
    ]


@router.get("/traces")
async def traces(session: SessionDep, days: int = Query(7, ge=1, le=90), limit: int = Query(15, ge=1, le=50)):
    """A7: links into Langfuse: the latest chat messages, and the slowest and most expensive LLM calls."""
    since, _, _ = _window(days)
    recent = (
        await session.execute(
            select(Doubt, User.full_name).join(User, User.id == Doubt.student_id).order_by(Doubt.id.desc()).limit(limit)
        )
    ).all()

    def call(u: LLMUsage) -> dict:
        return {
            "id": u.id,
            "at": u.created_at.isoformat(),
            "feature": u.feature,
            "latency_ms": u.latency_ms,
            "cost_usd": u.cost_usd,
            "tokens": u.input_tokens + u.output_tokens,
            "attempts": u.attempts,
            "status": u.status,
            "trace_url": trace_url(u.trace_id),
        }

    base = select(LLMUsage).where(LLMUsage.created_at >= since)
    slowest = (await session.scalars(base.order_by(LLMUsage.latency_ms.desc()).limit(10))).all()
    priciest = (await session.scalars(base.order_by(LLMUsage.cost_usd.desc()).limit(10))).all()
    return {
        "langfuse": tracing_enabled(),
        "recent": [
            {
                "id": d.id,
                "at": d.created_at.isoformat() if d.created_at else None,
                "user": name,
                "question": d.question,
                "intent": d.intent,
                "status": d.status,
                "latency_ms": d.latency_ms,
                "cost_usd": d.cost_usd,
                "trace_url": trace_url(d.trace_id),
            }
            for d, name in recent
        ],
        "slowest": [call(u) for u in slowest],
        "priciest": [call(u) for u in priciest],
    }
