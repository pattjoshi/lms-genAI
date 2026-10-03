"""Retrieval evaluation: does the right chunk come back for each question?

    uv run python -m app.evals.retrieval              # top_k = RAG_TOP_K
    uv run python -m app.evals.retrieval --k 3 --save

Metrics:
- hit@k  share of questions where a chunk of the expected topic is in the top k
- MRR    mean reciprocal rank: 1/rank of the first correct chunk (1.0 = always first)
- no-answer accuracy: for off-topic questions, is the best score below RAG_MIN_SCORE?

Retrieval is measured separately from answer quality on purpose: if the right chunk
isn't retrieved, no prompt or model can fix the answer. Change one thing at a time
(CHUNK_SIZE, CHUNK_OVERLAP, top k...), re-index, and re-run this to see the effect.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime

import yaml
from sqlalchemy import select

from app.config import REPO_ROOT, get_settings
from app.db import SessionLocal, engine
from app.models import Role, User
from app.rag import vectorstore
from app.rag.retriever import retrieve

QUESTIONS = REPO_ROOT / "evals" / "retrieval_questions.yaml"
RESULTS_DIR = REPO_ROOT / "evals" / "results"


def first_correct_rank(sources: list[dict], course: str, module: int, topic: str) -> int | None:
    prefix = f"{course}_M{module}_"
    for s in sources:
        if (s.get("file_name") or "").startswith(prefix) and s.get("topic") == topic:
            return s["rank"]
    return None


async def run(k: int, save: bool) -> int:
    settings = get_settings()
    items = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    rows, ranks, no_answer_ok = [], [], []

    async with SessionLocal() as session:
        # Evaluate as the admin: retrieval quality is measured over ALL courses.
        admin = await session.scalar(select(User).where(User.role == Role.admin).limit(1))
        if admin is None:
            print("No admin user found. Run: uv run python -m app.seed --reset", file=sys.stderr)
            return 1
        for item in items:
            result = await retrieve(session, admin, item["question"], top_k=k)
            top = result.top_score or 0.0
            if item.get("expect") == "no_answer":
                ok = top < settings.rag_min_score
                no_answer_ok.append(ok)
                rows.append((item["id"], "no-answer", f"top={top:.3f}", "OK" if ok else "LEAK", item["question"]))
                continue
            rank = first_correct_rank(result.sources, item["course"], item["module"], item["topic"])
            ranks.append(rank)
            got = result.sources[0]["topic"] if result.sources else "-"
            rows.append((item["id"], f"rank={rank or '-'}", f"top={top:.3f}", item["topic"], f"(#1: {got})"))

    n = len(ranks)
    hit = {kk: sum(1 for r in ranks if r and r <= kk) / n for kk in (1, 3, k)}
    mrr = sum(1 / r for r in ranks if r) / n

    print(f"\nRetrieval eval  k={k}  chunk_size={settings.chunk_size}  overlap={settings.chunk_overlap}")
    print("-" * 100)
    for row in rows:
        print("  ".join(str(c) for c in row))
    print("-" * 100)
    print(f"hit@1 {hit[1]:.2f}   hit@3 {hit[3]:.2f}   hit@{k} {hit[k]:.2f}   MRR {mrr:.3f}   ({n} questions)")
    if no_answer_ok:
        ok, total = sum(no_answer_ok), len(no_answer_ok)
        print(f"no-answer accuracy {ok}/{total} (threshold RAG_MIN_SCORE={settings.rag_min_score})")

    if save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"retrieval-{datetime.now():%Y%m%d-%H%M%S}.json"
        out.write_text(
            json.dumps(
                {
                    "k": k,
                    "chunk_size": settings.chunk_size,
                    "chunk_overlap": settings.chunk_overlap,
                    "hit": hit,
                    "mrr": mrr,
                    "no_answer_ok": sum(no_answer_ok),
                    "rows": rows,
                },
                indent=2,
            )
        )
        print(f"Saved {out.relative_to(REPO_ROOT)}")

    await vectorstore.close()
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int, default=get_settings().rag_top_k)
    parser.add_argument("--save", action="store_true", help="write results to evals/results/")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.k, args.save)))
