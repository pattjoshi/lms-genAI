"""Teacher review of the concept graph (Phase 3b): approve, edit, reject, merge, fix prerequisites.

The LLM proposes, a human decides. Every decision is stored on the graph itself, so a later
re-extraction respects it (see store.py and resolve.py):

    concept  draft -> approved   students can see it in learning paths
             draft -> rejected   hidden, and never re-created by a re-run
    edge     draft               used in learning paths while both ends are approved
             rejected            never used, kept as a tombstone so a re-run doesn't revive it
             approved            added by a teacher: survives re-processing and file deletion

Publishing = approving: learning paths only walk approved concepts (T8). That keeps review
to one click per concept; teachers only touch an edge when it is wrong.
"""

from neo4j import AsyncManagedTransaction

from app.graph.names import clean_name, concept_key
from app.graph.store import MAX_PATH, driver


class ReviewError(Exception):
    """A review action that can't be done (unknown concept, cycle, other course...). HTTP 409/404."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.message = message
        self.status = status


async def concept_course(uid: str) -> int | None:
    records, _, _ = await driver().execute_query(
        "MATCH (c:Concept {uid: $uid}) RETURN c.course_id AS course_id", uid=uid
    )
    return records[0]["course_id"] if records else None


async def update_concept(
    uid: str, *, name: str | None = None, definition: str | None = None, status: str | None = None
) -> None:
    """Rename keeps the uid (links stay valid) and remembers the old name as an alias, so the
    next extraction that says the old name still lands on this node."""
    if name is not None:
        name = clean_name(name)
        if not concept_key(name):
            raise ReviewError("The name is empty.", 422)
    if status is not None and status not in ("draft", "approved", "rejected"):
        raise ReviewError("Unknown status.", 422)
    await driver().execute_query(
        """MATCH (c:Concept {uid: $uid})
           SET c.aliases = CASE WHEN $name IS NULL OR $name = c.name OR c.name IN c.aliases THEN c.aliases
                                ELSE c.aliases + c.name END
           SET c.name = coalesce($name, c.name),
               c.definition = coalesce($definition, c.definition),
               c.status = coalesce($status, c.status),
               c.reviewed_at = datetime()""",
        uid=uid,
        name=name,
        definition=clean_name(definition, 500) if definition else None,
        status=status,
    )


async def approve_drafts(course_id: int) -> int:
    """'Approve all': for a teacher who has read the list and only rejected the bad ones."""
    records, _, _ = await driver().execute_query(
        """MATCH (c:Concept {course_id: $course_id, status: 'draft'})
           SET c.status = 'approved', c.reviewed_at = datetime()
           RETURN count(c) AS n""",
        course_id=course_id,
    )
    return records[0]["n"]


# ---------------------------------------------------------------------------
# Prerequisite edges
# ---------------------------------------------------------------------------


async def _would_cycle(tx: AsyncManagedTransaction, a: str, b: str) -> bool:
    """Would a -> b close a loop? Rejected edges don't count: learning paths never use them."""
    record = await (
        await tx.run(
            f"""MATCH (a:Concept {{uid: $a}}), (b:Concept {{uid: $b}})
                RETURN EXISTS {{ MATCH (b)-[r:REQUIRES*1..{MAX_PATH}]->(a)
                                 WHERE all(x IN r WHERE x.status <> 'rejected') }} AS cycle""",
            a=a,
            b=b,
        )
    ).single()
    return bool(record and record["cycle"])


async def _add_edge(tx: AsyncManagedTransaction, a: str, b: str) -> None:
    if a == b:
        raise ReviewError("A concept can't be its own prerequisite.")
    record = await (
        await tx.run(
            "MATCH (a:Concept {uid: $a}), (b:Concept {uid: $b}) RETURN a.course_id = b.course_id AS same_course",
            a=a,
            b=b,
        )
    ).single()
    if record is None:
        raise ReviewError("Concept not found.", 404)
    if not record["same_course"]:
        raise ReviewError("Both concepts must belong to the same course.")
    if await _would_cycle(tx, a, b):
        raise ReviewError("That would make a loop: the prerequisite already depends on this concept.")
    await tx.run(
        """MATCH (a:Concept {uid: $a}), (b:Concept {uid: $b})
           MERGE (a)-[r:REQUIRES]->(b)
           ON CREATE SET r.document_ids = []
           SET r.status = 'approved'""",
        a=a,
        b=b,
    )


async def add_prerequisite(uid: str, prerequisite_uid: str) -> None:
    async with driver().session() as session:
        await session.execute_write(_add_edge, uid, prerequisite_uid)


async def set_prerequisite_status(uid: str, prerequisite_uid: str, status: str) -> None:
    if status not in ("approved", "rejected"):
        raise ReviewError("Unknown status.", 422)
    if status == "approved":  # re-approving a rejected edge must pass the cycle check again
        return await add_prerequisite(uid, prerequisite_uid)
    records, _, _ = await driver().execute_query(
        """MATCH (:Concept {uid: $a})-[r:REQUIRES]->(:Concept {uid: $b})
           SET r.status = 'rejected' RETURN count(r) AS n""",
        a=uid,
        b=prerequisite_uid,
    )
    if not records[0]["n"]:
        raise ReviewError("That prerequisite link doesn't exist.", 404)


# ---------------------------------------------------------------------------
# Merge: two nodes are the same concept -> one node
# ---------------------------------------------------------------------------


async def _merge(tx: AsyncManagedTransaction, source: str, target: str) -> dict:
    if source == target:
        raise ReviewError("Pick a different concept to merge into.")
    nodes = await (
        await tx.run(
            """MATCH (s:Concept {uid: $s}), (t:Concept {uid: $t})
               RETURN s.course_id = t.course_id AS same_course, s.name AS name, s.aliases AS aliases,
                      s.definition AS definition""",
            s=source,
            t=target,
        )
    ).single()
    if nodes is None:
        raise ReviewError("Concept not found.", 404)
    if not nodes["same_course"]:
        raise ReviewError("Only concepts of the same course can be merged.")

    # Move every link of the source to the target. Done link by link (no APOC in Community).
    outgoing = await (
        await tx.run(
            """MATCH (:Concept {uid: $s})-[r:REQUIRES]->(p:Concept)
               RETURN p.uid AS other, r.document_ids AS docs, r.status AS status""",
            s=source,
        )
    ).data()
    incoming = await (
        await tx.run(
            """MATCH (p:Concept)-[r:REQUIRES]->(:Concept {uid: $s})
               RETURN p.uid AS other, r.document_ids AS docs, r.status AS status""",
            s=source,
        )
    ).data()
    explained = await (
        await tx.run(
            """MATCH (:Concept {uid: $s})-[e:EXPLAINED_IN]->(d:Document)
               RETURN d.id AS doc, e.section AS section, e.chunk_indexes AS chunk_indexes,
                      e.pages AS pages, e.evidence AS evidence""",
            s=source,
        )
    ).data()

    skipped = []
    edges = [(target, e["other"], e) for e in outgoing] + [(e["other"], target, e) for e in incoming]
    for a, b, e in edges:
        if a == b:
            continue  # source <-> target link becomes a self-loop: drop it
        if e["status"] != "rejected" and await _would_cycle(tx, a, b):
            skipped.append(f"{a} -> {b}")
            continue
        await tx.run(
            """MATCH (a:Concept {uid: $a}), (b:Concept {uid: $b})
               MERGE (a)-[r:REQUIRES]->(b)
               ON CREATE SET r.document_ids = $docs, r.status = $status
               ON MATCH SET r.document_ids = r.document_ids + [d IN $docs WHERE NOT d IN r.document_ids],
                            r.status = CASE WHEN 'rejected' IN [r.status, $status] THEN 'rejected'
                                            WHEN 'approved' IN [r.status, $status] THEN 'approved'
                                            ELSE 'draft' END""",
            a=a,
            b=b,
            docs=e["docs"] or [],
            status=e["status"] or "draft",
        )
    for e in explained:
        await tx.run(
            """MATCH (t:Concept {uid: $t}), (d:Document {id: $doc})
               MERGE (t)-[x:EXPLAINED_IN]->(d)
               ON CREATE SET x.section = $section, x.chunk_indexes = $chunk_indexes, x.pages = $pages,
                             x.evidence = $evidence""",
            t=target,
            **e,
        )
    names = [nodes["name"], *(nodes["aliases"] or [])]
    await tx.run(
        """MATCH (t:Concept {uid: $t})
           SET t.aliases = t.aliases + [n IN $names WHERE NOT n IN t.aliases AND n <> t.name],
               t.definition = coalesce(t.definition, $definition)
           WITH t
           MATCH (s:Concept {uid: $s}) DETACH DELETE s
           WITH t
           MATCH (c:Concept {possible_duplicate_of: $s}) SET c.possible_duplicate_of = NULL""",
        t=target,
        s=source,
        names=names,
        definition=nodes["definition"],
    )
    return {"merged_into": target, "links_skipped": skipped}


async def merge_concepts(source: str, target: str) -> dict:
    """The source's names become aliases of the target, so a re-extraction that says either
    name lands on the target from now on."""
    async with driver().session() as session:
        return await session.execute_write(_merge, source, target)
