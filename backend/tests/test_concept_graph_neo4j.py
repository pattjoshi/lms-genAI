"""The Cypher in app/graph/store.py against a real Neo4j. Skipped when Neo4j isn't running.

Uses a negative course id, so it never touches real course data, and cleans up after itself.
"""

import pytest
from neo4j.exceptions import ServiceUnavailable

from app.graph import store
from app.graph.store import DocMeta, Explained, NodeWrite

COURSE = -42


def _node(key, explained=True):
    return NodeWrite(
        uid=f"{COURSE}:{key}",
        key=key,
        name=key.title(),
        definition=f"About {key}." if explained else None,
        explained=Explained("S", [0], [1], "quote") if explained else None,
    )


async def _cleanup():
    await store.driver().execute_query("MATCH (n) WHERE n.course_id = $c DETACH DELETE n", c=COURSE)


@pytest.fixture
async def graph():
    try:
        await store.driver().verify_connectivity()
    except (ServiceUnavailable, OSError, ValueError):
        await store.close()
        pytest.skip("Neo4j is not running")
    await _cleanup()
    yield
    await _cleanup()
    await store.close()


async def test_write_reprocess_and_remove(graph):
    a = DocMeta(-1, COURSE, 0, "a.txt")
    b = DocMeta(-2, COURSE, 0, "b.txt")
    u = lambda k: f"{COURSE}:{k}"  # noqa: E731
    await store.write_document(
        a, [_node("chain rule"), _node("derivative", explained=False)], [(u("chain rule"), u("derivative"))]
    )
    await store.write_document(
        b, [_node("backpropagation"), _node("chain rule", explained=False)], [(u("backpropagation"), u("chain rule"))]
    )

    g = await store.course_graph(COURSE)
    assert {n["name"]: n["mentioned_only"] for n in g["nodes"]} == {
        "Backpropagation": False,
        "Chain Rule": False,
        "Derivative": True,
    }
    assert len(g["edges"]) == 2

    # Re-processing a file with the same result changes nothing
    await store.write_document(
        a, [_node("chain rule"), _node("derivative", explained=False)], [(u("chain rule"), u("derivative"))]
    )
    assert len((await store.course_graph(COURSE))["edges"]) == 2

    # A cycle is refused: derivative -> backpropagation would close backprop -> chain rule -> derivative
    written = await store.write_document(
        DocMeta(-3, COURSE, 0, "c.txt"), [_node("derivative")], [(u("derivative"), u("backpropagation"))]
    )
    assert written["edges"] == 0 and written["cycles_skipped"]

    # Removing file a: chain rule is still explained in... nothing, but backprop needs it -> kept, mentioned only
    await store.remove_document(-1, COURSE)
    g = await store.course_graph(COURSE)
    names = {n["name"]: n["mentioned_only"] for n in g["nodes"]}
    assert names["Chain Rule"] is True
    assert "Derivative" in names  # file c explains it
    assert [(e["source"], e["target"]) for e in g["edges"]] == [(u("backpropagation"), u("chain rule"))]


async def test_approved_concepts_survive_their_file(graph):
    doc = DocMeta(-1, COURSE, 0, "a.txt")
    await store.write_document(doc, [_node("recursion")], [])
    await store.driver().execute_query("MATCH (c:Concept {uid: $u}) SET c.status = 'approved'", u=f"{COURSE}:recursion")
    await store.remove_document(-1, COURSE)
    assert [n["name"] for n in (await store.course_graph(COURSE))["nodes"]] == ["Recursion"]
