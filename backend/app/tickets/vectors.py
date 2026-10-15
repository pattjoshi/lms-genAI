"""Small vector helpers for Phase 5: cosine similarity and grouping by meaning.

Tickets, knowledge-base answers and teacher insights compare at most a few thousand short questions, so
the vectors live in Postgres (a JSON column) and are compared here in Python. That keeps the logic easy
to read and test. With many more rows you would move them into a vector index: a second Qdrant
collection, or pgvector inside Postgres.
"""

import math
from dataclasses import dataclass, field


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def nearest(vec: list[float], items: list[tuple[object, list[float]]], min_sim: float, k: int) -> list[tuple]:
    """The k items most similar to `vec`, at least `min_sim`, best first: [(item, similarity)]."""
    scored = [(item, cosine(vec, v)) for item, v in items if v]
    return sorted([x for x in scored if x[1] >= min_sim], key=lambda x: -x[1])[:k]


@dataclass
class Group:
    members: list = field(default_factory=list)
    total: list[float] = field(default_factory=list)  # sum of the member vectors: same direction as the centroid

    def add(self, item: object, vec: list[float]) -> None:
        self.members.append(item)
        self.total = [a + b for a, b in zip(self.total, vec, strict=True)] if self.total else list(vec)


def group(items: list[tuple[object, list[float]]], min_sim: float) -> list[Group]:
    """Greedy grouping ("leader clustering"): each item joins the group whose centre it is most similar to, if
    that is at least `min_sim`, otherwise it starts a new group. One pass, no number of groups to choose, and
    the threshold has a plain meaning ("these questions mean the same"). The order of items matters a little;
    for a teacher's list of questions that is a fair price for simplicity. Largest groups first.

    (Cosine ignores length, so comparing with the SUM of the vectors is the same as comparing with their mean.)"""
    groups: list[Group] = []
    for item, vec in items:
        best, best_sim = None, min_sim
        for g in groups:
            sim = cosine(vec, g.total)
            if sim >= best_sim:
                best, best_sim = g, sim
        if best is None:
            best = Group()
            groups.append(best)
        best.add(item, vec)
    return sorted(groups, key=lambda g: -len(g.members))
