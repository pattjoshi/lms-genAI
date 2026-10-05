"""Retrieval evaluation: does the right chunk come back for each question?

    uv run python -m app.evals.retrieval                   # the pipeline as configured in .env
    uv run python -m app.evals.retrieval --compare         # every Phase 2 step on/off, side by side
    uv run python -m app.evals.retrieval --mode dense      # one mode (dense, hybrid, dense+rerank, hybrid+rerank, full)
    uv run python -m app.evals.retrieval --k 3 --save      # top 3, write results to evals/results/

Metrics:
- hit@k  share of questions where a chunk of the expected topic is in the top k
- MRR    mean reciprocal rank: 1/rank of the first correct chunk (1.0 = always first)
- per category hit@k: semantic, keyword, paraphrase, follow_up (see the YAML file)
- no-answer accuracy: for off-topic questions, is NOTHING marked relevant?

Retrieval is measured separately from answer quality on purpose: if the right chunk
isn't retrieved, no prompt or model can fix the answer. Change one thing at a time,
re-run this, and keep the change only if the numbers say so.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

import yaml
from sqlalchemy import select

from app.config import REPO_ROOT, get_settings
from app.db import SessionLocal, engine
from app.models import Role, User
from app.rag import vectorstore
from app.rag.retriever import RetrievalOptions, retrieve

QUESTIONS = REPO_ROOT / "evals" / "retrieval_questions.yaml"
RESULTS_DIR = REPO_ROOT / "evals" / "results"
CATEGORIES = ["semantic", "keyword", "paraphrase", "follow_up"]

# Each mode adds one step, so the difference between two rows is what that step is worth.
MODES = {
    "dense": RetrievalOptions.baseline(),  # Phase 1
    "hybrid": RetrievalOptions(hybrid=True, rerank=False, rewrite=False, corrective=False),
    "dense+rerank": RetrievalOptions(hybrid=False, rerank=True, rewrite=False, corrective=False),
    "hybrid+rerank": RetrievalOptions(hybrid=True, rerank=True, rewrite=False, corrective=False),
    "full": RetrievalOptions(hybrid=True, rerank=True, rewrite=True, corrective=True),
}


def first_correct_rank(sources: list[dict], course: str, module: int, topic: str) -> int | None:
    prefix = f"{course}_M{module}_"
    for s in sources:
        if (s.get("file_name") or "").startswith(prefix) and s.get("topic") == topic:
            return s["rank"]
    return None


@dataclass
class ModeResult:
    mode: str
    k: int
    ranks: dict[str, int | None] = field(default_factory=dict)  # question id -> rank of first correct chunk
    categories: dict[str, str] = field(default_factory=dict)
    no_answer_ok: dict[str, bool] = field(default_factory=dict)
    rows: list[tuple] = field(default_factory=list)
    # Relevance scores, to check the threshold: correct chunk of answerable vs best of off-topic
    answerable_scores: list[float] = field(default_factory=list)
    off_topic_scores: list[float] = field(default_factory=list)
    score_kind: str = "cosine"
    rerank_error: str | None = None
    ms: list[int] = field(default_factory=list)
    llm_cost_usd: float = 0.0

    def hit(self, kk: int, category: str | None = None) -> float | None:
        ranks = [r for q, r in self.ranks.items() if category is None or self.categories[q] == category]
        return sum(1 for r in ranks if r and r <= kk) / len(ranks) if ranks else None

    def mrr(self) -> float:
        return sum(1 / r for r in self.ranks.values() if r) / len(self.ranks) if self.ranks else 0.0

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "hit@1": self.hit(1),
            "hit@3": self.hit(3),
            f"hit@{self.k}": self.hit(self.k),
            "mrr": self.mrr(),
            "by_category": {c: self.hit(self.k, c) for c in CATEGORIES},
            "no_answer_ok": sum(self.no_answer_ok.values()),
            "no_answer_total": len(self.no_answer_ok),
            "avg_ms": int(sum(self.ms) / len(self.ms)) if self.ms else 0,
            "llm_cost_usd": self.llm_cost_usd,
            "rerank_error": self.rerank_error,
        }


async def run_mode(session, admin: User, items: list[dict], mode: str, opts: RetrievalOptions, k: int) -> ModeResult:
    res = ModeResult(mode=mode, k=k)
    for item in items:
        history = [(q, "") for q in item.get("history", [])]
        started = time.perf_counter()
        r = await retrieve(session, admin, item["question"], top_k=k, history=history, options=opts)
        res.ms.append(int((time.perf_counter() - started) * 1000))
        res.llm_cost_usd += r.llm_cost_usd
        res.rerank_error = res.rerank_error or r.search.rerank_error
        reranked = r.search.reranked
        res.score_kind = "rerank" if reranked else "cosine"

        def relevance(src: dict, reranked: bool = reranked) -> float:
            value = src.get("rerank_score") if reranked else src.get("score")
            return value if value is not None else 0.0

        searched = f'  -> "{r.retried_with or r.query}"' if (r.rewritten or r.retried_with) else ""
        if item.get("expect") == "no_answer":
            ok = not r.has_context
            res.no_answer_ok[item["id"]] = ok
            best = max((relevance(s) for s in r.sources), default=0.0)
            res.off_topic_scores.append(best)
            res.rows.append((item["id"], "no-answer", f"best={best:.3f}", "OK" if ok else "LEAK", item["question"]))
            continue
        rank = first_correct_rank(r.sources, item["course"], item["module"], item["topic"])
        res.ranks[item["id"]] = rank
        res.categories[item["id"]] = item.get("category", "semantic")
        if rank:
            res.answerable_scores.append(relevance(r.sources[rank - 1]))
        got = r.sources[0]["topic"] if r.sources else "-"
        res.rows.append((item["id"], f"rank={rank or '-'}", item["topic"], f"(#1: {got}){searched}"))
    return res


def _fmt(x: float | None) -> str:
    return "  -  " if x is None else f"{x:.2f}"


def print_mode(res: ModeResult) -> None:
    s = get_settings()
    print(f"\nMode: {res.mode}   k={res.k}   chunk_size={s.chunk_size}   candidates={s.rag_candidates}")
    print("-" * 100)
    for row in res.rows:
        print("  ".join(str(c) for c in row))
    print("-" * 100)
    print(
        f"hit@1 {res.hit(1):.2f}   hit@3 {res.hit(3):.2f}   hit@{res.k} {res.hit(res.k):.2f}   "
        f"MRR {res.mrr():.3f}   ({len(res.ranks)} questions)"
    )
    print(f"by category (hit@{res.k}): " + "   ".join(f"{c} {_fmt(res.hit(res.k, c))}" for c in CATEGORIES))
    if res.no_answer_ok:
        print(f"no-answer accuracy {sum(res.no_answer_ok.values())}/{len(res.no_answer_ok)}")
    print_threshold_check(res)


def print_threshold_check(res: ModeResult) -> None:
    """Is the relevance threshold in the right place? Compare the two score groups."""
    s = get_settings()
    threshold = s.rag_min_rerank_score if res.score_kind == "rerank" else s.rag_min_score
    name = "RAG_MIN_RERANK_SCORE" if res.score_kind == "rerank" else "RAG_MIN_SCORE"
    if not res.answerable_scores or not res.off_topic_scores:
        return
    low, high = min(res.answerable_scores), max(res.off_topic_scores)
    print(
        f"threshold check ({res.score_kind}): correct chunks score >= {low:.3f}, off-topic best <= {high:.3f}, "
        f"{name}={threshold}"
    )
    if high < low:
        print(f"  any threshold between {high:.3f} and {low:.3f} separates them.")
    else:
        print("  the groups overlap: no threshold is perfect; look at the questions near the boundary.")


def print_compare(results: list[ModeResult], k: int) -> None:
    print("\nComparison (same questions, same index; each row adds one step)\n")
    head = f"{'mode':14} {'hit@1':>6} {'hit@3':>6} {f'hit@{k}':>6} {'MRR':>6}  " + " ".join(
        f"{c[:9]:>9}" for c in CATEGORIES
    )
    print(head + f" {'no-ans':>7} {'avg ms':>7} {'LLM $':>9}")
    print("-" * len(head + " " * 26))
    for r in results:
        sm = r.summary()
        cats = " ".join(f"{_fmt(sm['by_category'][c]):>9}" for c in CATEGORIES)
        print(
            f"{r.mode:14} {sm['hit@1']:6.2f} {sm['hit@3']:6.2f} {sm[f'hit@{k}']:6.2f} {sm['mrr']:6.3f}  {cats} "
            f"{sm['no_answer_ok']:>3}/{sm['no_answer_total']:<3} {sm['avg_ms']:7} {sm['llm_cost_usd']:9.6f}"
        )
    print(f"(category columns = hit@{k} inside that category)")

    # Per question: where did the correct chunk land in each mode? Shows WHICH questions a step fixed.
    ids = list(results[0].ranks)
    print(f"\nRank of the first correct chunk per question ('-' = not in top {k})\n")
    print(f"{'id':5} " + " ".join(f"{r.mode:>13}" for r in results))
    for qid in ids:
        ranks = [r.ranks.get(qid) for r in results]
        if len(set(ranks)) == 1 and ranks[0] == 1:
            continue  # rank 1 everywhere: nothing to learn from this row
        print(f"{qid:5} " + " ".join(f"{(str(x) if x else '-'):>13}" for x in ranks))
    for r in results:
        if r.score_kind == "rerank" or r.mode == "dense":
            print(f"\n[{r.mode}] ", end="")
            print_threshold_check(r)
    errors = {r.rerank_error for r in results if r.rerank_error}
    if errors:
        print(f"\nWARNING: {errors.pop()}. The rerank rows above ran WITHOUT reranking.")


async def run(k: int, mode: str | None, compare: bool, save: bool) -> int:
    items = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    async with SessionLocal() as session:
        # Evaluate as the admin: retrieval quality is measured over ALL courses.
        admin = await session.scalar(select(User).where(User.role == Role.admin).limit(1))
        if admin is None:
            print("No admin user found. Run: uv run python -m app.seed --reset", file=sys.stderr)
            return 1
        if await vectorstore.ensure_collection() != "ok":
            print(f"The search index is in the Phase 1 format. {vectorstore.REINDEX_HINT}", file=sys.stderr)
            return 1

        if compare:
            selected = list(MODES.items())
        elif mode:
            selected = [(mode, MODES[mode])]
        else:
            selected = [("env", RetrievalOptions.from_settings())]
        results = []
        for name, opts in selected:
            print(f"Running {name}...", file=sys.stderr)
            results.append(await run_mode(session, admin, items, name, opts, k))

    if compare:
        print_compare(results, k)
    else:
        print_mode(results[0])

    if save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"retrieval-{datetime.now():%Y%m%d-%H%M%S}.json"
        settings = get_settings()
        payload = {
            "k": k,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "candidates": settings.rag_candidates,
            "reranker_model": settings.reranker_model,
            "modes": [{**r.summary(), "ranks": r.ranks, "rows": r.rows} for r in results],
        }
        out.write_text(json.dumps(payload, indent=2))
        print(f"Saved {out.relative_to(REPO_ROOT)}")

    await vectorstore.close()
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int, default=get_settings().rag_top_k)
    parser.add_argument("--mode", choices=list(MODES), help="run one mode instead of the .env settings")
    parser.add_argument("--compare", action="store_true", help="run every mode and print a comparison table")
    parser.add_argument("--save", action="store_true", help="write results to evals/results/")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.k, args.mode, args.compare, args.save)))
