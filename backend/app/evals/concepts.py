"""Concept extraction evaluation: does the graph match what the course authors wrote?

    uv run python -m app.evals.concepts              # all courses
    uv run python -m app.evals.concepts --course DL301 --show

Ground truth: data/course_source/<course>/m*.md. Every "## Topic" is a concept a student
should be able to find, and its "Prerequisites: A, B." line lists the expected edges.
The model only sees the rendered files, so this is a fair test.

Metrics (per course and in total):
- topic recall   share of topics that became a concept explained by a file
- edge recall    share of expected prerequisites found as a direct REQUIRES edge
- path recall    ... or reachable through a chain of edges (A -> X -> B also gives a valid order)
- edge precision share of extracted edges between two known topics that the authors' prerequisites
                 support (directly or through a chain). Edges to finer concepts are not judged.
- concepts/topic granularity: ~1-4 is useful for learning paths; 10 means "every term"

Recall is easy to buy with many concepts and many edges; precision keeps it honest.
Change the prompt or the thresholds, run `app.graph.backfill --force`, then this again.
"""

import argparse
import asyncio
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select

from app.config import REPO_ROOT
from app.db import SessionLocal, engine
from app.graph import store
from app.graph.names import concept_key
from app.models import Course

SOURCE_DIR = REPO_ROOT / "data" / "course_source"
_PREREQ = re.compile(r"^Prerequisites:\s*(?P<list>.+?)\.?(\s+This is .*)?$")


def ground_truth(course_code: str) -> tuple[list[str], list[tuple[str, str]]]:
    """-> (topic names, [(topic, prerequisite)]) from the course's markdown sources."""
    topics, edges, current = [], [], None
    for path in sorted((SOURCE_DIR / course_code).glob("m*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
                topics.append(current)
            elif current and (m := _PREREQ.match(line.strip())):
                listed = m.group("list")
                if not listed.lower().startswith("none"):
                    edges += [(current, p.strip()) for p in listed.split(",") if p.strip()]
    return topics, edges


def reachable(adjacency: dict[str, set[str]], start: str) -> set[str]:
    seen, stack = set(), [start]
    while stack:
        for nxt in adjacency.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


@dataclass
class Score:
    course: str
    topics: int = 0
    topics_found: int = 0
    edges: int = 0
    edges_direct: int = 0
    edges_path: int = 0
    judged: int = 0  # extracted edges between two known topics
    supported: int = 0
    concepts: int = 0
    mentioned_only: int = 0
    possible_duplicates: int = 0


def score_course(code: str, graph: dict, show: bool = False) -> Score:
    topics, gt_edges = ground_truth(code)
    s = Score(code, topics=len(topics), edges=len(gt_edges))

    # concept key (name or alias) -> node uid
    uid_of: dict[str, str] = {}
    for n in graph["nodes"]:
        if n["status"] == "rejected":
            continue
        for name in [n["name"], *n["aliases"]]:
            uid_of.setdefault(concept_key(name), n["uid"])
    explained = {n["uid"] for n in graph["nodes"] if not n["mentioned_only"] and n["status"] != "rejected"}
    s.concepts = len(explained)
    s.mentioned_only = sum(1 for n in graph["nodes"] if n["mentioned_only"])
    s.possible_duplicates = sum(1 for n in graph["nodes"] if n["possible_duplicate_of"])

    adjacency: dict[str, set[str]] = defaultdict(set)
    for e in graph["edges"]:
        adjacency[e["source"]].add(e["target"])

    missing = []
    for t in topics:
        if uid_of.get(concept_key(t)) in explained:
            s.topics_found += 1
        else:
            missing.append(t)

    missed_edges = []
    for topic, prereq in gt_edges:
        a, b = uid_of.get(concept_key(topic)), uid_of.get(concept_key(prereq))
        if a and b and b in adjacency[a]:
            s.edges_direct += 1
        if a and b and b in reachable(adjacency, a):
            s.edges_path += 1
        else:
            missed_edges.append(f"{topic} -> {prereq}")

    # Precision, judged only where we know the truth: both ends are named topics/prerequisites.
    truth: dict[str, set[str]] = defaultdict(set)
    for topic, prereq in gt_edges:
        truth[concept_key(topic)].add(concept_key(prereq))
    known_keys = {concept_key(t) for t in topics} | {concept_key(p) for _, p in gt_edges}
    keys_of: dict[str, set[str]] = defaultdict(set)  # a merged node has several names
    for key, uid in uid_of.items():
        if key in known_keys:
            keys_of[uid].add(key)
    unsupported = []
    for e in graph["edges"]:
        a_keys, b_keys = keys_of.get(e["source"]), keys_of.get(e["target"])
        if not a_keys or not b_keys:
            continue
        s.judged += 1
        if any(b in reachable(truth, a) for a in a_keys for b in b_keys):
            s.supported += 1
        else:
            unsupported.append(f"{min(a_keys)} -> {min(b_keys)}")

    if show:
        print(f"\n{code}")
        print("  topics not found:   ", ", ".join(missing) or "-")
        print("  prerequisites missed:", "; ".join(missed_edges) or "-")
        print("  edges not supported: ", "; ".join(unsupported) or "-")
    return s


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "    -"


def print_table(scores: list[Score]) -> None:
    total = Score("TOTAL")
    for s in scores:
        for f in ("topics", "topics_found", "edges", "edges_direct", "edges_path", "judged", "supported"):
            setattr(total, f, getattr(total, f) + getattr(s, f))
        total.concepts += s.concepts
        total.mentioned_only += s.mentioned_only
        total.possible_duplicates += s.possible_duplicates
    print(
        f"\n{'course':8} {'topic rec':>9} {'edge rec':>9} {'path rec':>9} {'edge prec':>9} "
        f"{'concepts':>8} {'per topic':>9} {'mentioned':>9} {'dup?':>5}"
    )
    for s in [*scores, total]:
        per_topic = f"{s.concepts / s.topics:9.1f}" if s.topics else "        -"
        print(
            f"{s.course:8} {_pct(s.topics_found, s.topics):>9} {_pct(s.edges_direct, s.edges):>9} "
            f"{_pct(s.edges_path, s.edges):>9} {_pct(s.supported, s.judged):>9} {s.concepts:8} {per_topic} "
            f"{s.mentioned_only:9} {s.possible_duplicates:5}"
        )


async def main(course_code: str | None, show: bool) -> int:
    async with SessionLocal() as session:
        query = select(Course).order_by(Course.code)
        if course_code:
            query = query.where(Course.code == course_code.upper())
        courses = (await session.scalars(query)).all()
    scores = []
    for c in courses:
        if not (SOURCE_DIR / c.code).is_dir():
            continue
        scores.append(score_course(c.code, await store.course_graph(c.id), show))
    print_table(scores)
    if not any(s.concepts for s in scores):
        print("\nThe graph is empty. Run: uv run python -m app.graph.backfill")
    await store.close()
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", help="only this course code, e.g. DL301")
    parser.add_argument("--show", action="store_true", help="list missed topics/edges and unsupported edges")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.course, args.show)))
