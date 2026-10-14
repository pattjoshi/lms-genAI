"""Teacher review + learning paths against a real Neo4j. Skipped when Neo4j isn't running."""

import pytest
from neo4j.exceptions import ServiceUnavailable

from app.graph import paths, review, store
from app.graph.resolve import key_index
from app.graph.store import DocMeta, Explained, NodeWrite

COURSE = -43


def u(key: str) -> str:
    return f"{COURSE}:{key}"


def node(key: str, explained=True) -> NodeWrite:
    return NodeWrite(
        uid=u(key),
        key=key,
        name=key.title(),
        definition=f"About {key}.",
        explained=Explained("S", [0], [1], "quote") if explained else None,
    )


@pytest.fixture
async def graph():
    try:
        await store.driver().verify_connectivity()
    except (ServiceUnavailable, OSError, ValueError):
        await store.close()
        pytest.skip("Neo4j is not running")
    cleanup = "MATCH (n) WHERE n.course_id IN [$c, $c - 1] DETACH DELETE n"
    await store.driver().execute_query(cleanup, c=COURSE)
    # backprop -> chain rule -> derivative ; backprop -> gradient descent ; "backward pass" = duplicate
    await store.write_document(
        DocMeta(-11, COURSE, 0, "dl.txt"),
        [node(k) for k in ("backpropagation", "chain rule", "derivative", "gradient descent", "backward pass")],
        [
            (u("backpropagation"), u("chain rule")),
            (u("chain rule"), u("derivative")),
            (u("backpropagation"), u("gradient descent")),
            (u("backward pass"), u("derivative")),
        ],
    )
    yield
    await store.driver().execute_query(cleanup, c=COURSE)
    await store.close()


async def _order(uid, statuses=("approved",)):
    g = await paths.subgraph(uid, list(statuses))
    return paths.study_order([n["uid"] for n in g["nodes"]], g["edges"], {}), g


async def test_only_approved_concepts_and_unrejected_edges_reach_students(graph):
    order, _ = await _order(u("backpropagation"))
    assert order == []  # all drafts: nothing published yet

    assert await review.approve_drafts(COURSE) == 5
    order, _ = await _order(u("backpropagation"))
    assert order.index(u("derivative")) < order.index(u("chain rule")) < order.index(u("backpropagation"))
    assert len(order) == 4

    await review.set_prerequisite_status(u("backpropagation"), u("gradient descent"), "rejected")
    await review.update_concept(u("derivative"), status="rejected")
    order, _ = await _order(u("backpropagation"))
    assert order == [u("chain rule"), u("backpropagation")]


async def test_merge_moves_links_and_keeps_the_old_name_as_alias(graph):
    result = await review.merge_concepts(u("backward pass"), u("backpropagation"))
    assert result["merged_into"] == u("backpropagation")
    g = await store.course_graph(COURSE)
    by_uid = {n["uid"]: n for n in g["nodes"]}
    assert u("backward pass") not in by_uid
    assert "Backward Pass" in by_uid[u("backpropagation")]["aliases"]
    edges = {(e["source"], e["target"]) for e in g["edges"]}
    assert (u("backpropagation"), u("derivative")) in edges  # moved from the duplicate
    # re-extraction now resolves the old name to the merged node
    known = await store.course_concepts(COURSE)
    assert key_index(known)["backward pass"].uid == u("backpropagation")


async def test_teacher_edges_refuse_cycles_and_survive_file_deletion(graph):
    with pytest.raises(review.ReviewError, match="loop"):
        await review.add_prerequisite(u("derivative"), u("backpropagation"))
    with pytest.raises(review.ReviewError):
        await review.add_prerequisite(u("derivative"), u("derivative"))
    await review.add_prerequisite(u("gradient descent"), u("derivative"))
    await review.update_concept(u("derivative"), name="Derivatives", status="approved")
    await store.remove_document(-11, COURSE)
    g = await store.course_graph(COURSE)
    names = {n["name"]: n for n in g["nodes"]}
    assert "Derivatives" in names and "Derivative" in names["Derivatives"]["aliases"]  # rename kept old name
    edges = {(e["source"], e["target"], e["status"]) for e in g["edges"]}
    assert (u("gradient descent"), u("derivative"), "approved") in edges  # teacher's edge survived
