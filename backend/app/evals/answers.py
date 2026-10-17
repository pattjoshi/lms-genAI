"""Answer-quality evaluation: guardrail -> retrieval -> answer, graded (Phase 7).

    uv run python -m app.evals.answers                       # run, save, compare with the previous run
    uv run python -m app.evals.answers --label "chunk 600"   # name the run (what did you change?)
    uv run python -m app.evals.answers --set RAG_RERANK=false --label "no rerank"   # try a setting, no .env edit
    uv run python -m app.evals.answers --only Q11,Q12 --no-save                     # a quick look at a few
    uv run python -m app.evals.answers --baseline evals/results/answers-20261017-101500.json

One command answers every question in evals/answer_questions.yaml the way the chat does, grades the answers,
saves the run (eval_runs table + evals/results/answers-*.json) and prints each metric next to the previous
run's, marked better / worse / same. The admin dashboard (AI quality & cost) shows the same runs.

Metrics (the "RAG triad" plus the checks around it):
- context precision  of the excerpts given to the LLM, are the right ones (the question's topic) ranked first?
                     average precision over the used excerpts; from the labels, no LLM
- context recall     did an excerpt of the right topic reach the LLM at all? (labels; the eval set's
                     reference answers each come from one topic)
- faithfulness       share of the answer's claims the excerpts support, judged claim by claim by an LLM,
                     with each "supported" verdict's quoted evidence checked in code
- relevance          does it answer the question asked? 1-5 by the LLM judge, shown as 0-1
- correctness        does it agree with the teacher-written reference answer? (LLM judge)
- answer rate        answerable questions that got an answer (not "I couldn't find this", not blocked)
- no-answer ok       uncovered / off-topic questions that were NOT answered from general knowledge
- guardrail          off-topic and injection questions refused; answerable ones wrongly refused (over-blocking)
- judge checks       planted bad answers the judge must catch: if it misses them, don't trust its scores

Why faithfulness and correctness are different: an answer can be faithful to the wrong excerpt (retrieval
failed) or correct from general knowledge (not faithful: a hallucination that happened to be right).
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import select

from app.config import REPO_ROOT, get_settings
from app.db import SessionLocal, engine
from app.guardrails.input import check_input
from app.llm.service import chat, chat_structured
from app.llm.tracing import current_trace_id, init_tracing, score, shutdown_tracing, trace
from app.models import EvalRun, Role, User
from app.prompts.judge import FAITHFULNESS_SYSTEM, FAITHFULNESS_USER, RELEVANCE_SYSTEM, RELEVANCE_USER
from app.prompts.rag_answer import NO_ANSWER, format_excerpt
from app.rag import vectorstore
from app.rag.answer import rag_messages
from app.rag.retriever import retrieve

QUESTIONS = REPO_ROOT / "evals" / "answer_questions.yaml"
RESULTS_DIR = REPO_ROOT / "evals" / "results"

# name -> (label, higher is better?). The order is the order of the comparison table.
METRICS: dict[str, tuple[str, bool]] = {
    "context_precision": ("context precision", True),
    "context_recall": ("context recall", True),
    "faithfulness": ("faithfulness", True),
    "relevance": ("relevance", True),
    "correctness": ("correctness", True),
    "answer_rate": ("answer rate", True),
    "no_answer_ok": ("no-answer ok", True),
    "guard_blocked": ("guardrail: attacks/off-topic refused", True),
    "over_blocked": ("guardrail: good questions refused", False),
    "judge_checks": ("judge checks passed", True),
    "avg_ms": ("avg latency (ms)", False),
    "cost_usd": ("cost (USD)", False),
}


# ---------------------------------------------------------------------------
# Metrics computed in code
# ---------------------------------------------------------------------------


def is_expected(source: dict, item: dict) -> bool:
    """Is this excerpt from the topic the question is about? (FAQ answers count by course.)"""
    if source.get("faq"):
        return source.get("course_code") == item["course"]
    prefix = f"{item['course']}_M{item['module']}_"
    return (source.get("file_name") or "").startswith(prefix) and source.get("topic") == item["topic"]


def context_precision(used: list[dict], item: dict) -> float:
    """Average precision: precision@i averaged over the positions i that hold a right excerpt.
    [right, wrong, wrong] = 1.0; [wrong, wrong, right] = 0.33. No right excerpt = 0."""
    hits, total = 0, 0.0
    for i, source in enumerate(used, start=1):
        if is_expected(source, item):
            hits += 1
            total += hits / i
    return round(total / hits, 3) if hits else 0.0


def context_recall(used: list[dict], item: dict) -> float:
    return 1.0 if any(is_expected(s, item) for s in used) else 0.0


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def evidence_found(evidence: str, excerpts: str) -> bool:
    """The judge's quote must really be in the excerpts (like the Phase 3 quote check). Short quotes are
    compared whole; long ones by their first 12 words, so a small paraphrase at the end still counts."""
    words = _norm(evidence).split()
    if len(words) < 3:
        return False
    return " ".join(words[:12]) in _norm(excerpts)


def is_answered(answer: str) -> bool:
    return bool(answer.strip()) and not answer.strip().startswith(NO_ANSWER)


# ---------------------------------------------------------------------------
# The judge (LLM)
# ---------------------------------------------------------------------------


class Claim(BaseModel):
    claim: str
    supported: bool
    evidence: str = Field(description="The excerpt sentence that supports it, copied exactly. Empty if none.")


class FaithfulnessGrade(BaseModel):
    claims: list[Claim]


class RelevanceGrade(BaseModel):
    relevance: Literal[1, 2, 3, 4, 5]
    correct: bool
    reason: str


@dataclass
class Grade:
    faithfulness: float | None
    claims: list[dict]
    relevance: float
    correct: bool
    reason: str
    evidence_mismatch: int
    cost_usd: float


def faithfulness_score(claims: list[Claim], excerpts: str) -> tuple[float | None, int, list[dict]]:
    """(supported share, claims whose 'evidence' isn't in the excerpts, claims as dicts). A claim the judge
    marked supported with made-up evidence counts as unsupported: the judge can hallucinate too."""
    out, supported, mismatch = [], 0, 0
    for c in claims:
        ok = c.supported and evidence_found(c.evidence, excerpts)
        if c.supported and not ok:
            mismatch += 1
        supported += ok
        out.append({"claim": c.claim, "supported": ok})
    return (round(supported / len(claims), 3) if claims else None), mismatch, out


async def judge(session, user: User, question: str, reference: str, excerpts: str, answer: str) -> Grade:
    s = get_settings()
    model = s.eval_judge_model
    faith, r1 = await chat_structured(
        session,
        messages=[
            SystemMessage(FAITHFULNESS_SYSTEM),
            HumanMessage(FAITHFULNESS_USER.format(excerpts=excerpts, answer=answer)),
        ],
        schema=FaithfulnessGrade,
        feature="eval_judge",
        user=user,
        max_tokens=s.eval_max_output_tokens,
        model=model,
    )
    rel, r2 = await chat_structured(
        session,
        messages=[
            SystemMessage(RELEVANCE_SYSTEM),
            HumanMessage(RELEVANCE_USER.format(question=question, reference=reference or "(none)", answer=answer)),
        ],
        schema=RelevanceGrade,
        feature="eval_judge",
        user=user,
        max_tokens=s.eval_max_output_tokens,
        model=model,
    )
    score_f, mismatch, claims = faithfulness_score(faith.claims, excerpts)
    return Grade(
        faithfulness=score_f,
        claims=claims,
        relevance=round((rel.relevance - 1) / 4, 3),
        correct=rel.correct,
        reason=rel.reason,
        evidence_mismatch=mismatch,
        cost_usd=r1.cost_usd + r2.cost_usd,
    )


def judge_check_passed(expect: str, grade: Grade) -> bool:
    if expect == "unfaithful":
        return grade.faithfulness is not None and grade.faithfulness < 0.5
    if expect == "off_question":
        return grade.relevance < 0.5
    raise ValueError(f"unknown judge check {expect!r}")


# ---------------------------------------------------------------------------
# One question
# ---------------------------------------------------------------------------


async def run_item(session, user: User, item: dict) -> tuple[dict, str]:
    """Answer one question like the chat does, then grade it. Returns (result row, excerpts text)."""
    expect = item.get("expect", "answer")
    row: dict = {"id": item["id"], "expect": expect, "question": item["question"]}
    started = time.perf_counter()
    cost = 0.0
    with trace("eval_answer", user, "eval", input={"id": item["id"], "question": item["question"]}):
        row["trace_id"] = current_trace_id()
        verdict = await check_input(session, user, item["question"])
        cost += verdict.cost_usd
        row["guard"] = None if verdict.allowed else verdict.kind
        row["guard_method"] = verdict.method
        if not verdict.allowed:
            row.update(answered=False, answer=verdict.reply, ms=int((time.perf_counter() - started) * 1000))
            row["cost_usd"] = round(cost, 6)
            return row, ""

        retrieval = await retrieve(session, user, item["question"])
        cost += retrieval.cost_usd
        used = [x for x in retrieval.sources if x["used"]]
        excerpts = "\n\n".join(format_excerpt(i, x) for i, x in enumerate(used, start=1))
        answer = NO_ANSWER
        if used:
            result = await chat(
                session,
                messages=rag_messages(user, item["question"], retrieval),
                feature="eval_answer",
                user=user,
                max_tokens=get_settings().rag_max_output_tokens,
            )
            answer, cost = result.text, cost + result.cost_usd
        row["ms"] = int((time.perf_counter() - started) * 1000)
        row["answer"] = answer
        row["answered"] = is_answered(answer)

        if expect == "answer":
            row["context_precision"] = context_precision(used, item)
            row["context_recall"] = context_recall(used, item)
            if row["answered"]:
                grade = await judge(session, user, item["question"], item.get("reference", ""), excerpts, answer)
                cost += grade.cost_usd
                row.update(
                    faithfulness=grade.faithfulness,
                    relevance=grade.relevance,
                    correctness=1.0 if grade.correct else 0.0,
                    reason=grade.reason,
                    claims=grade.claims,
                    evidence_mismatch=grade.evidence_mismatch,
                )
                for name in ("faithfulness", "relevance", "correctness"):
                    if row[name] is not None:
                        score(row["trace_id"], name, row[name])
    row["cost_usd"] = round(cost, 6)
    return row, excerpts


async def run_judge_check(session, user: User, check: dict, of: dict, excerpts: str) -> dict:
    grade = await judge(session, user, of["question"], of.get("reference", ""), excerpts, check["answer"])
    return {
        "id": check["id"],
        "expect": check["expect"],
        "passed": judge_check_passed(check["expect"], grade),
        "faithfulness": grade.faithfulness,
        "relevance": grade.relevance,
        "cost_usd": round(grade.cost_usd, 6),
    }


# ---------------------------------------------------------------------------
# Summary and comparison
# ---------------------------------------------------------------------------


def _avg(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else None


def summarize(items: list[dict], checks: list[dict]) -> dict:
    answerable = [r for r in items if r["expect"] == "answer"]
    refuse = [r for r in items if r["expect"] in ("no_answer", "off_topic", "injection")]
    attacks = [r for r in items if r["expect"] in ("off_topic", "injection")]
    good = [r for r in items if r["expect"] in ("answer", "no_answer")]
    return {
        "context_precision": _avg([r.get("context_precision") for r in answerable]),
        "context_recall": _avg([r.get("context_recall") for r in answerable]),
        "faithfulness": _avg([r.get("faithfulness") for r in answerable]),
        "relevance": _avg([r.get("relevance") for r in answerable]),
        "correctness": _avg([r.get("correctness") for r in answerable]),
        "answer_rate": _avg([1.0 if r["answered"] else 0.0 for r in answerable]),
        "no_answer_ok": _avg([0.0 if r["answered"] else 1.0 for r in refuse]),
        "guard_blocked": _avg([1.0 if r.get("guard") else 0.0 for r in attacks]),
        "over_blocked": sum(1 for r in good if r.get("guard")),
        "judge_checks": _avg([1.0 if c["passed"] else 0.0 for c in checks]),
        "avg_ms": int(sum(r.get("ms", 0) for r in items) / len(items)) if items else 0,
        "cost_usd": round(sum(r.get("cost_usd", 0) for r in items) + sum(c["cost_usd"] for c in checks), 6),
        "questions": len(items),
    }


def compare(now: dict, before: dict, margin: float) -> list[dict]:
    """One row per metric: before, now, change, and better / worse / same. Rates move by more than `margin`
    to count; latency by more than 20 %; cost by more than 10 %; a count by at least 1."""
    rows = []
    for key, (label, higher_better) in METRICS.items():
        a, b = before.get(key), now.get(key)
        if a is None or b is None:
            rows.append({"metric": key, "label": label, "before": a, "now": b, "change": None, "verdict": "-"})
            continue
        change = round(b - a, 6)
        if key == "avg_ms":
            threshold = 0.2 * max(a, 1)
        elif key == "cost_usd":
            threshold = 0.1 * max(a, 1e-9)
        elif key == "over_blocked":
            threshold = 0.5
        else:
            threshold = margin
        if abs(change) <= threshold:
            verdict = "same"
        else:
            verdict = "better" if (change > 0) == higher_better else "worse"
        rows.append({"metric": key, "label": label, "before": a, "now": b, "change": change, "verdict": verdict})
    return rows


def regressions(now_items: list[dict], before_items: list[dict]) -> list[str]:
    """Questions that got worse, so you know which answers to read."""
    before = {r["id"]: r for r in before_items}
    out = []
    for r in now_items:
        b = before.get(r["id"])
        if b is None:
            continue
        if r["expect"] == "answer":
            for key in ("context_recall", "faithfulness", "correctness", "relevance"):
                x, y = b.get(key), r.get(key)
                if x is not None and y is not None and y < x - 0.25:
                    out.append(f"{r['id']}: {key} {x:.2f} -> {y:.2f}  ({r.get('question', '')})")
            if b.get("answered") and not r.get("answered"):
                out.append(f"{r['id']}: no longer answered  ({r.get('question', '')})")
        elif r["expect"] in ("off_topic", "injection") and b.get("guard") and not r.get("guard"):
            out.append(f"{r['id']}: no longer refused  ({r.get('question', '')})")
        if r["expect"] in ("answer", "no_answer") and r.get("guard") and not b.get("guard"):
            out.append(f"{r['id']}: now wrongly refused  ({r.get('question', '')})")
    return out


def _fmt(key: str, v) -> str:
    if v is None:
        return "-"
    if key == "avg_ms" or key == "over_blocked":
        return f"{int(v)}"
    if key == "cost_usd":
        return f"{v:.4f}"
    return f"{v:.2f}"


def print_run(items: list[dict], checks: list[dict], summary: dict) -> None:
    print("\nPer question")
    print("-" * 100)
    for r in items:
        if r["expect"] == "answer":
            cols = [f"ctxP {_fmt('', r.get('context_precision'))}", f"ctxR {_fmt('', r.get('context_recall'))}"]
            if r.get("guard"):
                cols.append(f"REFUSED ({r['guard']})")
            elif not r["answered"]:
                cols.append("not answered")
            else:
                cols += [
                    f"faith {_fmt('', r.get('faithfulness'))}",
                    f"rel {_fmt('', r.get('relevance'))}",
                    "correct" if r.get("correctness") else "WRONG",
                ]
        else:
            ok = bool(r.get("guard")) if r["expect"] in ("off_topic", "injection") else not r["answered"]
            how = (
                f"refused by {r['guard_method']}" if r.get("guard") else ("answered" if r["answered"] else "no answer")
            )
            cols = [r["expect"], how, "OK" if ok else "MISS"]
        print(f"{r['id']:4}  " + "  ".join(cols) + f"   {r['question'][:60]}")
    for c in checks:
        print(
            f"{c['id']:4}  judge check ({c['expect']}): {'passed' if c['passed'] else 'FAILED'}"
            f"  faith {_fmt('', c['faithfulness'])}  rel {_fmt('', c['relevance'])}"
        )
    print("-" * 100)
    for key, (label, _) in METRICS.items():
        print(f"{label:38} {_fmt(key, summary.get(key))}")


def print_compare(rows: list[dict], before_label: str, regressed: list[str]) -> None:
    print(f"\nCompared with {before_label}\n")
    print(f"{'metric':38} {'before':>8} {'now':>8} {'change':>8}  verdict")
    print("-" * 75)
    for r in rows:
        if r["change"] is None:
            change = "-"
        elif r["metric"] in ("avg_ms", "over_blocked"):
            change = f"{int(r['change']):+d}"
        elif r["metric"] == "cost_usd":
            change = f"{r['change']:+.4f}"
        else:
            change = f"{r['change']:+.2f}"
        mark = {"better": "better ✓", "worse": "WORSE ✗"}.get(r["verdict"], r["verdict"])
        print(
            f"{r['label']:38} {_fmt(r['metric'], r['before']):>8} {_fmt(r['metric'], r['now']):>8} {change:>8}  {mark}"
        )
    better = sum(r["verdict"] == "better" for r in rows)
    worse = sum(r["verdict"] == "worse" for r in rows)
    print(f"\n{better} better, {worse} worse.")
    if regressed:
        print("\nQuestions that got worse (read these answers):")
        for line in regressed:
            print("  " + line)


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def apply_overrides(pairs: list[str]) -> dict:
    """--set KEY=VALUE: change a setting for this run only (validated like .env)."""
    s = get_settings()
    done = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        name = key.strip().lower()
        if name not in type(s).model_fields:
            raise SystemExit(f"Unknown setting {key!r} (use the .env name, e.g. RAG_RERANK=false)")
        parsed = TypeAdapter(type(s).model_fields[name].annotation).validate_python(value.strip() or None)
        setattr(s, name, parsed)
        done[key.strip().upper()] = value.strip()
    return done


def run_config(overrides: dict) -> dict:
    s = get_settings()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT, timeout=5
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = ""
    return {
        "commit": commit or None,
        "model": s.openai_chat_model,
        "judge_model": s.eval_judge_model or s.openai_chat_model,
        "chunk_size": s.chunk_size,
        "top_k": s.rag_top_k,
        "hybrid": s.rag_hybrid,
        "rerank": s.rag_rerank,
        "rewrite": s.rag_rewrite,
        "corrective": s.rag_corrective,
        "guardrails": s.guardrails,
        "overrides": overrides,
    }


async def load_baseline(session, path: str | None) -> tuple[dict, list, str] | None:
    if path:
        file = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
        data = json.loads(file.read_text(encoding="utf-8"))
        return data["summary"], data["items"], path
    run = await session.scalar(select(EvalRun).where(EvalRun.kind == "answers").order_by(EvalRun.id.desc()).limit(1))
    if run is None:
        return None
    label = f"run #{run.id}" + (f" ({run.label})" if run.label else "") + f", {run.created_at:%Y-%m-%d %H:%M}"
    return run.summary, run.items, label


async def run(args) -> int:
    overrides = apply_overrides(args.set or [])
    init_tracing(get_settings())
    data = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    items = data["questions"]
    if args.only:
        wanted = set(args.only.split(","))
        items = [q for q in items if q["id"] in wanted]
    checks_def = data.get("judge_checks", []) if not args.only else []

    async with SessionLocal() as session:
        admin = await session.scalar(select(User).where(User.role == Role.admin).limit(1))
        if admin is None:
            print("No admin user found. Run: uv run python -m app.seed --reset", file=sys.stderr)
            return 1
        if await vectorstore.ensure_collection() != "ok":
            print(f"The search index is in the Phase 1 format. {vectorstore.REINDEX_HINT}", file=sys.stderr)
            return 1
        baseline = None if args.no_compare else await load_baseline(session, args.baseline)

        rows, excerpts = [], {}
        for n, item in enumerate(items, start=1):
            print(f"[{n}/{len(items)}] {item['id']} {item['question'][:70]}", file=sys.stderr)
            row, text = await run_item(session, admin, item)
            rows.append(row)
            excerpts[item["id"]] = text
        by_id = {q["id"]: q for q in data["questions"]}
        checks = []
        for check in checks_def:
            if excerpts.get(check["of"]):
                checks.append(await run_judge_check(session, admin, check, by_id[check["of"]], excerpts[check["of"]]))
            else:
                print(f"{check['id']}: skipped, {check['of']} got no excerpts", file=sys.stderr)

        summary = summarize(rows, checks)
        print_run(rows, checks, summary)
        if baseline:
            before_summary, before_items, before_label = baseline
            print_compare(
                compare(summary, before_summary, get_settings().eval_better_margin),
                before_label,
                regressions(rows, before_items),
            )
        elif not args.no_compare:
            print("\nNo earlier run to compare with: this run is the baseline for the next one.")

        if not args.no_save:
            config = run_config(overrides)
            record = EvalRun(
                kind="answers",
                label=args.label,
                config=config,
                summary=summary,
                items=rows + [{**c, "judge_check": True} for c in checks],
                cost_usd=summary["cost_usd"],
            )
            session.add(record)
            await session.commit()
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            out = RESULTS_DIR / f"answers-{datetime.now():%Y%m%d-%H%M%S}.json"
            payload = {"label": args.label, "config": config, "summary": summary, "items": rows, "judge_checks": checks}
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nSaved run #{record.id} and {out.relative_to(REPO_ROOT)}")

    shutdown_tracing()
    await vectorstore.close()
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", help="what changed in this run, shown in comparisons and the dashboard")
    parser.add_argument("--set", action="append", metavar="KEY=VALUE", help="override a setting for this run")
    parser.add_argument("--only", help="comma-separated question ids (judge checks are skipped)")
    parser.add_argument("--baseline", help="compare with this saved JSON file instead of the previous run")
    parser.add_argument("--no-compare", action="store_true", help="don't compare with an earlier run")
    parser.add_argument("--no-save", action="store_true", help="don't save this run")
    sys.exit(asyncio.run(run(parser.parse_args())))
