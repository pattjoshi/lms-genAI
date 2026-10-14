"""Learning paths (Phase 3b): "I don't understand X" -> what to study, in order.

    1. find X:     exact name/alias -> words in common -> embeddings (only if the rules found nothing)
    2. walk back:  every concept X needs, directly or through others: (x)-[:REQUIRES*]->(p)
    3. sort:       topological order, prerequisites first (Kahn's algorithm); ties in course order
    4. link:       each step points at the file + page that explains it (S10), or at another
                   course when this one only mentions it

Students only ever see APPROVED concepts and edges a teacher didn't reject. The graph is an
LLM's proposal until a human has looked at it.
"""

import heapq
from dataclasses import dataclass, field

from app.graph.names import concept_key
from app.graph.store import MAX_PATH, driver
from app.ingest.tagger import cosine


@dataclass
class Candidate:
    uid: str
    name: str
    course_id: int
    definition: str | None = None
    aliases: list[str] = field(default_factory=list)
    embedding: list[float] | None = None


async def searchable(course_ids: list[int], statuses: list[str]) -> list[Candidate]:
    records, _, _ = await driver().execute_query(
        """MATCH (c:Concept) WHERE c.course_id IN $course_ids AND c.status IN $statuses
           RETURN c.uid AS uid, c.name AS name, c.course_id AS course_id, c.definition AS definition,
                  coalesce(c.aliases, []) AS aliases, c.embedding AS embedding""",
        course_ids=course_ids,
        statuses=statuses,
    )
    return [Candidate(**r.data()) for r in records]


def match_by_rules(query: str, candidates: list[Candidate], limit: int = 5) -> list[tuple[Candidate, float]]:
    """Cheap, deterministic matching first (same habit as topic tagging in Phase 1).
    1.0 = the name or an alias, 0.9 = one name contains the other, else share of words in common."""
    q = concept_key(query)
    if not q:
        return []
    q_words = set(q.split())
    scored: list[tuple[Candidate, float]] = []
    for c in candidates:
        keys = {concept_key(n) for n in [c.name, *c.aliases]}
        if q in keys:
            score = 1.0
        elif any(len(q) >= 3 and (q in k or k in q) for k in keys if len(k) >= 3):
            score = 0.9
        else:
            score = max(len(q_words & set(k.split())) / len(q_words | set(k.split())) for k in keys)
        if score >= 0.5:
            scored.append((c, round(score, 3)))
    scored.sort(key=lambda x: (-x[1], x[0].name))
    return scored[:limit]


def match_by_embedding(
    vector: list[float], candidates: list[Candidate], min_similarity: float, limit: int = 5
) -> list[tuple[Candidate, float]]:
    scored = [(c, round(cosine(vector, c.embedding), 3)) for c in candidates if c.embedding]
    scored = [x for x in scored if x[1] >= min_similarity]
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def study_order(uids: list[str], edges: list[tuple[str, str]], rank: dict[str, tuple]) -> list[str]:
    """Topological sort: a concept comes after everything it requires.

    `edges` are (concept, prerequisite). Among concepts that are ready at the same time, the one
    that comes first in the course (`rank`, e.g. module + position in the file) goes first,
    so the path reads like the course does. Kahn's algorithm with a priority queue.
    """
    needs = {u: 0 for u in uids}  # number of prerequisites not placed yet
    unlocks: dict[str, list[str]] = {u: [] for u in uids}
    for concept, prereq in edges:
        if concept in needs and prereq in needs:
            needs[concept] += 1
            unlocks[prereq].append(concept)
    ready = [(rank.get(u, ()), u) for u, n in needs.items() if n == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        _, u = heapq.heappop(ready)
        order.append(u)
        for nxt in unlocks[u]:
            needs[nxt] -= 1
            if needs[nxt] == 0:
                heapq.heappush(ready, (rank.get(nxt, ()), nxt))
    if len(order) != len(uids):  # a cycle slipped in (shouldn't: writes check for them)
        order += sorted(set(uids) - set(order), key=lambda u: rank.get(u, ()))
    return order


async def subgraph(uid: str, statuses: list[str]) -> dict:
    """The target, everything it needs (through visible concepts and non-rejected edges), and
    where each one is explained."""
    nodes, _, _ = await driver().execute_query(
        f"""MATCH (t:Concept {{uid: $uid}}) WHERE t.status IN $statuses
            MATCH (t)-[r:REQUIRES*0..{MAX_PATH}]->(p:Concept)
            WHERE all(x IN r WHERE x.status <> 'rejected')
              AND all(x IN r WHERE endNode(x).status IN $statuses)
            WITH DISTINCT p
            OPTIONAL MATCH (p)-[e:EXPLAINED_IN]->(d:Document)
            RETURN p.uid AS uid, p.name AS name, p.key AS key, p.definition AS definition,
                   p.course_id AS course_id, p.status AS status,
                   [x IN collect(CASE WHEN d IS NULL THEN NULL ELSE
                       {{document_id: d.id, file_name: d.file_name, module_id: d.module_id,
                         pages: e.pages, section: e.section, chunk: e.chunk_indexes[0]}} END)
                    WHERE x IS NOT NULL] AS materials""",
        uid=uid,
        statuses=statuses,
    )
    uids = [r["uid"] for r in nodes]
    edges, _, _ = await driver().execute_query(
        """MATCH (a:Concept)-[r:REQUIRES]->(b:Concept)
           WHERE a.uid IN $uids AND b.uid IN $uids AND r.status <> 'rejected'
           RETURN a.uid AS concept, b.uid AS prerequisite""",
        uids=uids,
    )
    return {"nodes": [r.data() for r in nodes], "edges": [(r["concept"], r["prerequisite"]) for r in edges]}


async def explained_elsewhere(keys: list[str], course_ids: list[int], exclude_course: int) -> dict[str, list[dict]]:
    """A concept this course only mentions (e.g. Linear Regression in Deep Learning) may be
    explained in another course the student can read: same key, approved, has material."""
    if not keys:
        return {}
    records, _, _ = await driver().execute_query(
        """MATCH (c:Concept)-[e:EXPLAINED_IN]->(d:Document)
           WHERE c.key IN $keys AND c.course_id IN $course_ids AND c.course_id <> $exclude
             AND c.status = 'approved'
           RETURN c.key AS key, c.course_id AS course_id, d.file_name AS file_name, d.module_id AS module_id,
                  e.pages AS pages, e.section AS section""",
        keys=keys,
        course_ids=course_ids,
        exclude=exclude_course,
    )
    out: dict[str, list[dict]] = {}
    for r in records:
        out.setdefault(r["key"], []).append(r.data())
    return out
