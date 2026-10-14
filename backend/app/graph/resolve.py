"""Entity resolution: does a concept from a new file already exist in the course graph?

    1. Same key (spelling variants, see names.py) or a known alias -> the existing node
    2. Embedding similarity >= CONCEPT_MERGE_THRESHOLD           -> the existing node,
                                                                    new name kept as alias
    3. similarity >= CONCEPT_SUGGEST_THRESHOLD                    -> a NEW node, flagged
                                                                    "possible duplicate of"
    4. otherwise                                                  -> a NEW node

Why two thresholds: a wrong merge silently glues two concepts together (and their
prerequisites), which is worse than a duplicate a teacher can merge with one click.
So only near-certain matches merge automatically; the grey zone goes to a human.

A concept the teacher REJECTED (Phase 3 review) is matched too, and then skipped, so
re-processing a file never brings it back.

Pure functions: no database, no API. The caller embeds and writes.
"""

from dataclasses import dataclass, field

from app.graph.names import concept_key
from app.ingest.tagger import cosine


@dataclass
class Known:
    """A concept node that is already in the course graph."""

    uid: str
    key: str
    name: str
    status: str  # draft | approved | rejected
    aliases: list[str] = field(default_factory=list)
    embedding: list[float] | None = None


@dataclass
class Decision:
    uid: str
    action: str  # existing | merged | new | rejected
    similarity: float | None = None
    possible_duplicate_of: str | None = None  # uid, only for action == "new"


def concept_uid(course_id: int, key: str) -> str:
    return f"{course_id}:{key}"


def key_index(known: list[Known]) -> dict[str, Known]:
    """key -> node, for names AND aliases."""
    index: dict[str, Known] = {}
    for k in known:
        index.setdefault(k.key, k)
        for alias in k.aliases:
            index.setdefault(concept_key(alias), k)
    return index


def resolve(
    course_id: int,
    keys: list[str],
    vectors: dict[str, list[float]],
    known: list[Known],
    *,
    merge_threshold: float,
    suggest_threshold: float,
) -> dict[str, Decision]:
    """Decide, for each concept key of the new file, which node it becomes.

    `vectors` holds embeddings only for keys that had no key match (the caller embeds just
    those, to save tokens). Greedy, in order: a new node joins the pool, so two synonyms
    inside the same file also end up as one node.
    """
    by_key = key_index(known)
    pool = [k for k in known if k.embedding]
    out: dict[str, Decision] = {}
    for key in keys:
        if key in out:
            continue
        hit = by_key.get(key)
        if hit is not None:
            out[key] = Decision(hit.uid, "rejected" if hit.status == "rejected" else "existing", 1.0)
            continue

        vector = vectors.get(key)
        best, best_sim = None, 0.0
        if vector is not None:
            for k in pool:
                sim = cosine(vector, k.embedding)
                if sim > best_sim:
                    best, best_sim = k, sim
        if best is not None and best_sim >= merge_threshold:
            action = "rejected" if best.status == "rejected" else "merged"
            out[key] = Decision(best.uid, action, round(best_sim, 4))
            by_key[key] = best
            continue

        uid = concept_uid(course_id, key)
        flagged = best.uid if best is not None and best_sim >= suggest_threshold else None
        out[key] = Decision(uid, "new", round(best_sim, 4) if best else None, flagged)
        node = Known(uid=uid, key=key, name=key, status="draft", embedding=vector)
        by_key[key] = node
        if vector is not None:
            pool.append(node)
    return out
