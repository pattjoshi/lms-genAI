"""Neo4j access for the concept graph (Phase 3).

The graph model:

    (:Concept {uid, course_id, key, name, aliases, definition, status, embedding,
               possible_duplicate_of})
        -[:REQUIRES {document_ids, status}]->      (:Concept)    "learn the target first"
        -[:EXPLAINED_IN {chunk_indexes, pages, evidence, section}]-> (:Document {id, file_name})

- `uid` = "<course_id>:<key>": one node per concept per course, and MERGE-safe.
- `status`: draft (from the LLM) -> approved / rejected (teacher review, next part of Phase 3).
- A concept with no EXPLAINED_IN link is "mentioned only": another concept needs it, but no
  file of this course explains it (e.g. "Linear Regression" in the deep learning course).
- Every REQUIRES edge remembers which files it came from, so re-processing or deleting a
  file removes exactly what that file added. Approved concepts/edges are never removed
  automatically: a human decision outranks a re-run of the model.

Why a graph database: "what must I learn before X?" is a variable-length path query
(`(x)-[:REQUIRES*]->(p)`), one line of Cypher, but a recursive CTE in SQL.
"""

from dataclasses import dataclass, field

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction

from app.config import get_settings
from app.graph.resolve import Known

_driver: AsyncDriver | None = None
_constraints_ready = False
MAX_PATH = 25  # longest prerequisite chain we look at when checking for cycles


def driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        s = get_settings()
        _driver = AsyncGraphDatabase.driver(
            s.neo4j_uri,
            auth=(s.neo4j_user, s.neo4j_password),
            # Neo4j warns about every property that doesn't exist yet (e.g. on an empty graph).
            notifications_min_severity="OFF",
        )
    return _driver


async def close() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def ensure_constraints() -> None:
    """Idempotent. A uniqueness constraint also creates the index used to look nodes up."""
    global _constraints_ready
    if _constraints_ready:
        return
    for statement in (
        "CREATE CONSTRAINT concept_uid IF NOT EXISTS FOR (c:Concept) REQUIRE c.uid IS UNIQUE",
        "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
        "CREATE INDEX concept_course IF NOT EXISTS FOR (c:Concept) ON (c.course_id)",
    ):
        await driver().execute_query(statement)
    _constraints_ready = True


@dataclass
class DocMeta:
    id: int
    course_id: int
    module_id: int
    file_name: str


@dataclass
class Explained:
    section: str | None
    chunk_indexes: list[int]
    pages: list[int]
    evidence: str


@dataclass
class NodeWrite:
    uid: str
    key: str
    name: str
    definition: str | None
    embedding: list[float] | None = None
    possible_duplicate_of: str | None = None
    aliases: list[str] = field(default_factory=list)
    explained: Explained | None = None  # None = only mentioned as a prerequisite in this file


async def course_concepts(course_id: int) -> list[Known]:
    records, _, _ = await driver().execute_query(
        """MATCH (c:Concept {course_id: $course_id})
           RETURN c.uid AS uid, c.key AS key, c.name AS name, c.status AS status,
                  coalesce(c.aliases, []) AS aliases, c.embedding AS embedding""",
        course_id=course_id,
    )
    return [Known(**r.data()) for r in records]


# ---------------------------------------------------------------------------
# Writing one document's concepts (one transaction: all or nothing)
# ---------------------------------------------------------------------------

_UNLINK_DOCUMENT = [
    "MATCH (:Concept)-[e:EXPLAINED_IN]->(:Document {id: $doc_id}) DELETE e",
    """MATCH (:Concept)-[r:REQUIRES]->(:Concept) WHERE $doc_id IN r.document_ids
       SET r.document_ids = [x IN r.document_ids WHERE x <> $doc_id]
       WITH r WHERE size(r.document_ids) = 0 AND r.status = 'draft'
       DELETE r""",
]

# Draft concepts that no file explains and no other concept needs are leftovers.
_DELETE_ORPHANS = """
MATCH (c:Concept {course_id: $course_id, status: 'draft'})
WHERE NOT (c)-[:EXPLAINED_IN]->() AND NOT (c)-[:REQUIRES]-()
DETACH DELETE c
RETURN count(c) AS n"""

_UPSERT_CONCEPT = """
MERGE (c:Concept {uid: $uid})
ON CREATE SET c.course_id = $course_id, c.key = $key, c.name = $name, c.status = 'draft',
              c.aliases = [], c.definition = $definition, c.embedding = $embedding,
              c.possible_duplicate_of = $possible_duplicate_of, c.created_at = datetime()
SET c.aliases = c.aliases + [a IN $aliases WHERE NOT a IN c.aliases AND a <> c.name],
    c.definition = CASE WHEN c.status = 'draft' AND c.definition IS NULL THEN $definition ELSE c.definition END,
    c.updated_at = datetime()"""

_LINK_EXPLAINED = """
MATCH (c:Concept {uid: $uid}), (d:Document {id: $doc_id})
MERGE (c)-[e:EXPLAINED_IN]->(d)
SET e.section = $section, e.chunk_indexes = $chunk_indexes, e.pages = $pages, e.evidence = $evidence"""

# Adding a -> b when b already (indirectly) requires a would make a loop: no valid study order.
_WOULD_CYCLE = f"""
MATCH (a:Concept {{uid: $a}}), (b:Concept {{uid: $b}})
RETURN EXISTS {{ MATCH (b)-[:REQUIRES*1..{MAX_PATH}]->(a) }} AS cycle"""

_ADD_REQUIRES = """
MATCH (a:Concept {uid: $a}), (b:Concept {uid: $b})
MERGE (a)-[r:REQUIRES]->(b)
ON CREATE SET r.document_ids = [$doc_id], r.status = 'draft'
ON MATCH SET r.document_ids = CASE WHEN $doc_id IN r.document_ids THEN r.document_ids
                                   ELSE r.document_ids + $doc_id END"""


async def _write(
    tx: AsyncManagedTransaction, doc: DocMeta, nodes: list[NodeWrite], edges: list[tuple[str, str]]
) -> dict:
    # Re-processing: forget what this file said last time, then write what it says now.
    for statement in _UNLINK_DOCUMENT:
        await tx.run(statement, doc_id=doc.id)
    await tx.run(
        """MERGE (d:Document {id: $id})
           SET d.course_id = $course_id, d.module_id = $module_id, d.file_name = $file_name""",
        id=doc.id,
        course_id=doc.course_id,
        module_id=doc.module_id,
        file_name=doc.file_name,
    )
    for n in nodes:
        await tx.run(
            _UPSERT_CONCEPT,
            uid=n.uid,
            course_id=doc.course_id,
            key=n.key,
            name=n.name,
            definition=n.definition,
            embedding=n.embedding,
            possible_duplicate_of=n.possible_duplicate_of,
            aliases=n.aliases,
        )
        if n.explained:
            e = n.explained
            await tx.run(
                _LINK_EXPLAINED,
                uid=n.uid,
                doc_id=doc.id,
                section=e.section,
                chunk_indexes=e.chunk_indexes,
                pages=e.pages,
                evidence=e.evidence,
            )
    added, cycles = 0, []
    for a, b in edges:
        record = await (await tx.run(_WOULD_CYCLE, a=a, b=b)).single()
        if record and record["cycle"]:
            cycles.append(f"{a} -> {b}")
            continue
        await tx.run(_ADD_REQUIRES, a=a, b=b, doc_id=doc.id)
        added += 1
    orphans = await (await tx.run(_DELETE_ORPHANS, course_id=doc.course_id)).single()
    return {"edges": added, "cycles_skipped": cycles, "orphans_removed": orphans["n"] if orphans else 0}


async def write_document(doc: DocMeta, nodes: list[NodeWrite], edges: list[tuple[str, str]]) -> dict:
    await ensure_constraints()
    async with driver().session() as session:
        return await session.execute_write(_write, doc, nodes, edges)


async def _remove(tx: AsyncManagedTransaction, doc_id: int, course_id: int) -> None:
    for statement in _UNLINK_DOCUMENT:
        await tx.run(statement, doc_id=doc_id)
    await tx.run("MATCH (d:Document {id: $doc_id}) DETACH DELETE d", doc_id=doc_id)
    await tx.run(_DELETE_ORPHANS, course_id=course_id)


async def remove_document(doc_id: int, course_id: int) -> None:
    """A file was deleted or replaced by a newer version: take out what it contributed."""
    async with driver().session() as session:
        await session.execute_write(_remove, doc_id, course_id)


# ---------------------------------------------------------------------------
# Reading (teacher views)
# ---------------------------------------------------------------------------


async def document_concepts(doc_id: int) -> list[dict]:
    records, _, _ = await driver().execute_query(
        """MATCH (c:Concept)-[e:EXPLAINED_IN]->(:Document {id: $doc_id})
           OPTIONAL MATCH (c)-[r:REQUIRES]->(p:Concept)
           WITH c, e, collect(CASE WHEN p IS NULL THEN NULL
                                   ELSE {uid: p.uid, name: p.name, status: r.status} END) AS prerequisites
           RETURN c.uid AS uid, c.name AS name, c.definition AS definition, c.status AS status,
                  coalesce(c.aliases, []) AS aliases, c.possible_duplicate_of AS possible_duplicate_of,
                  e.section AS section, e.pages AS pages, e.chunk_indexes AS chunk_indexes,
                  e.evidence AS evidence, prerequisites
           ORDER BY e.chunk_indexes[0], c.name""",
        doc_id=doc_id,
    )
    return [r.data() for r in records]


async def course_graph(course_id: int) -> dict:
    nodes, _, _ = await driver().execute_query(
        """MATCH (c:Concept {course_id: $course_id})
           OPTIONAL MATCH (c)-[:EXPLAINED_IN]->(d:Document)
           RETURN c.uid AS uid, c.name AS name, c.definition AS definition, c.status AS status,
                  coalesce(c.aliases, []) AS aliases, c.possible_duplicate_of AS possible_duplicate_of,
                  collect(d.file_name) AS files
           ORDER BY c.name""",
        course_id=course_id,
    )
    edges, _, _ = await driver().execute_query(
        """MATCH (a:Concept {course_id: $course_id})-[r:REQUIRES]->(b:Concept)
           RETURN a.uid AS source, b.uid AS target, r.status AS status, r.document_ids AS document_ids""",
        course_id=course_id,
    )
    out_nodes = [{**r.data(), "mentioned_only": not r["files"]} for r in nodes]
    return {"nodes": out_nodes, "edges": [r.data() for r in edges]}
