"""The SQL agent: plain English -> SQL -> rows -> answer + chart (Phase 6), as a LangGraph state machine.

    START ─▶ write_sql ─┬─▶ END                         not a data question, or asks to change data
                        └─▶ check ─┬─▶ run ─┬─▶ explain ─▶ END
                                   │        └─▶ write_sql   Postgres error: try again with the error
                                   └─▶ write_sql            validator error: try again with the error
                        (after SQL_AGENT_MAX_ATTEMPTS failed tries) ─▶ give_up ─▶ END

- write_sql   one structured LLM call: {answerable, sql, note}. On a retry it also sees its failed SQL
              and the exact error (self-correction).
- check       app/sql_agent/validate.py. A write (DELETE, DROP...) is refused at once, not retried.
- run         app/sql_agent/run.py: read-only user, row-level security, timeout, row limit.
- explain     no rows -> a fixed sentence (no LLM); else one LLM call for the answer. The chart is
              chosen by rules (chart.py).

Same reasoning as the chat graph (Phase 4): every path is known, so a fixed graph is cheaper and easier
to test than a free agent, and it can't loop: the retry edge counts attempts.
"""

import time
from datetime import UTC, datetime
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm import service as llm
from app.llm.service import LLMResult
from app.models import SqlQuery, User
from app.prompts import sql_agent as prompts
from app.sql_agent import run as runner
from app.sql_agent.chart import choose_chart
from app.sql_agent.describe import schema_text, scope_sentence, scope_summary
from app.sql_agent.validate import UnsafeSql, check_sql


class SqlDraft(BaseModel):
    answerable: bool = Field(description="false if the tables can't answer this, or it asks to change data")
    sql: str = Field(description="One PostgreSQL SELECT query, no semicolon. Empty when answerable is false")
    note: str = Field(description="Why it can't be answered, or one short assumption made. Can be empty")


class SqlState(TypedDict, total=False):
    session: AsyncSession
    user: User
    question: str
    schema: str
    tries: list[dict]  # [{sql, error, stage}], the last one has error None when it ran
    sql: str | None
    ok: bool  # the last check / run succeeded
    note: str
    result: runner.QueryResult | None
    status: str  # answered | no_rows | refused | failed
    answer: str
    chart: dict | None
    usage: dict[str, Any]


def _add_usage(state: SqlState, result: LLMResult) -> dict:
    usage = dict(state.get("usage") or {})
    usage["input_tokens"] = usage.get("input_tokens", 0) + result.input_tokens
    usage["output_tokens"] = usage.get("output_tokens", 0) + result.output_tokens
    usage["cost_usd"] = usage.get("cost_usd", 0.0) + result.cost_usd
    usage["llm_calls"] = usage.get("llm_calls", 0) + 1
    return usage


def sql_messages(user: User, question: str, schema: str, tries: list[dict], today: str) -> list[BaseMessage]:
    system = prompts.SQL_SYSTEM.format(
        name=user.full_name,
        role=user.role.value,
        user_id=user.id,
        scope=scope_sentence(user.role),
        today=today,
        schema=schema,
        examples=prompts.format_examples(user.id),
    )
    messages: list[BaseMessage] = [SystemMessage(system), HumanMessage(question)]
    for t in tries:
        if t.get("error"):
            messages += [AIMessage(t["sql"] or "(empty)"), HumanMessage(prompts.RETRY.format(**t))]
    return messages


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def write_sql(state: SqlState) -> dict:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.app_timezone)).strftime("%A %d %B %Y")
    draft, result = await llm.chat_structured(
        state["session"],
        messages=sql_messages(state["user"], state["question"], state["schema"], state.get("tries", []), today),
        schema=SqlDraft,
        feature="sql_write",
        user=state["user"],
        max_tokens=settings.sql_agent_max_output_tokens,
    )
    usage = _add_usage(state, result)
    if not draft.answerable or not draft.sql.strip():
        note = draft.note.strip() or "That isn't something the LMS data can answer."
        return {"status": "refused", "answer": note, "sql": None, "usage": usage}
    return {"sql": draft.sql, "note": draft.note.strip(), "usage": usage}


async def check(state: SqlState) -> dict:
    try:
        return {"sql": check_sql(state["sql"] or ""), "ok": True}
    except UnsafeSql as exc:
        tries = [*state.get("tries", []), {"sql": state["sql"], "error": exc.message, "stage": "check"}]
        if exc.kind == "write":
            return {"tries": tries, "ok": False, "status": "refused", "answer": prompts.WRITE_REFUSED}
        return {"tries": tries, "ok": False}


async def run(state: SqlState) -> dict:
    try:
        result = await runner.run_scoped(state["user"], state["sql"])
    except runner.QueryFailed as exc:
        tries = [*state.get("tries", []), {"sql": state["sql"], "error": exc.message, "stage": exc.stage}]
        if not exc.retryable:
            return {"tries": tries, "ok": False, "status": "failed", "answer": exc.message}
        return {"tries": tries, "ok": False}
    tries = [*state.get("tries", []), {"sql": state["sql"], "error": None, "stage": "run"}]
    return {"tries": tries, "ok": True, "result": result}


def _table(columns: list[str], rows: list[tuple]) -> str:
    lines = [" | ".join(columns)]
    lines += [" | ".join("" if v is None else str(runner.jsonable(v)) for v in row) for row in rows]
    return "\n".join(lines)


async def explain(state: SqlState) -> dict:
    result = state["result"]
    if not result.rows:
        return {"status": "no_rows", "answer": prompts.NO_ROWS, "chart": None}
    settings = get_settings()
    shown = result.rows[: settings.sql_agent_answer_rows]
    cut = ""
    if result.truncated:
        cut = f", cut off at {len(result.rows)}"
    if len(shown) < len(result.rows):
        cut += f"; showing the first {len(shown)}"
    user = state["user"]
    reply = await llm.chat(
        state["session"],
        messages=[
            SystemMessage(prompts.ANSWER_SYSTEM.format(role=user.role.value)),
            HumanMessage(
                prompts.ANSWER_USER.format(
                    question=state["question"],
                    count=len(result.rows),
                    cut=cut,
                    columns=", ".join(result.columns),
                    rows=_table(result.columns, shown),
                )
            ),
        ],
        feature="sql_answer",
        user=user,
        max_tokens=300,
    )
    return {
        "status": "answered",
        "answer": reply.text.strip(),
        "chart": choose_chart(result.columns, result.rows),
        "usage": _add_usage(state, reply),
    }


async def give_up(state: SqlState) -> dict:
    return {"status": "failed", "answer": prompts.GAVE_UP}


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


def _retry_or_give_up(state: SqlState) -> str:
    return "write_sql" if len(state.get("tries", [])) < get_settings().sql_agent_max_attempts else "give_up"


def after_write(state: SqlState) -> str:
    return END if state.get("status") == "refused" else "check"


def after_check(state: SqlState) -> str:
    if state.get("status") == "refused":
        return END
    return "run" if state["ok"] else _retry_or_give_up(state)


def after_run(state: SqlState) -> str:
    if state.get("status") == "failed":
        return END
    return "explain" if state["ok"] else _retry_or_give_up(state)


def build_graph():
    g = StateGraph(SqlState)
    g.add_node("write_sql", write_sql)
    g.add_node("check", check)
    g.add_node("run", run)
    g.add_node("explain", explain)
    g.add_node("give_up", give_up)
    g.add_edge(START, "write_sql")
    g.add_conditional_edges("write_sql", after_write, ["check", END])
    g.add_conditional_edges("check", after_check, ["run", "write_sql", "give_up", END])
    g.add_conditional_edges("run", after_run, ["explain", "write_sql", "give_up", END])
    g.add_edge("explain", END)
    g.add_edge("give_up", END)
    return g.compile()


graph = build_graph()


# ---------------------------------------------------------------------------
# Entry point (API and MCP)
# ---------------------------------------------------------------------------


async def ask(session: AsyncSession, user: User, question: str) -> dict:
    """Answer one question and save it (sql_queries). The caller commits."""
    started = time.perf_counter()
    schema = await schema_text(session)
    state: SqlState = await graph.ainvoke(
        {"session": session, "user": user, "question": question, "schema": schema, "tries": [], "usage": {}}
    )
    result: runner.QueryResult | None = state.get("result")
    tries = state.get("tries", [])
    usage = state.get("usage") or {}
    ran = result is not None
    row = SqlQuery(
        user_id=user.id,
        question=question,
        sql=state.get("sql") if ran else (tries[-1]["sql"] if tries else None),
        attempts=tries,
        status=state.get("status", "failed"),
        row_count=len(result.rows) if ran else 0,
        truncated=result.truncated if ran else False,
        answer=state.get("answer"),
        chart=state.get("chart"),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cost_usd=usage.get("cost_usd", 0.0),
        latency_ms=int((time.perf_counter() - started) * 1000),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    out = history_row(row)
    out.update(
        {
            "note": state.get("note") or "",
            "columns": result.columns if ran else [],
            "rows": [[runner.jsonable(v) for v in r] for r in result.rows] if ran else [],
            "query_ms": result.ms if ran else None,
            "llm_calls": usage.get("llm_calls", 0),
            "scope": scope_summary(user.role),
        }
    )
    return out


def history_row(q: SqlQuery) -> dict:
    return {
        "id": q.id,
        "question": q.question,
        "status": q.status,
        "sql": q.sql,
        "attempts": q.attempts or [],
        "answer": q.answer,
        "chart": q.chart,
        "row_count": q.row_count,
        "truncated": q.truncated,
        "input_tokens": q.input_tokens,
        "output_tokens": q.output_tokens,
        "cost_usd": round(q.cost_usd or 0, 6),
        "latency_ms": q.latency_ms,
        "created_at": q.created_at.isoformat() if q.created_at else None,
    }


async def history(session: AsyncSession, user: User, limit: int = 20) -> list[dict]:
    rows = await session.scalars(
        select(SqlQuery).where(SqlQuery.user_id == user.id).order_by(SqlQuery.id.desc()).limit(limit)
    )
    return [history_row(q) for q in rows]
