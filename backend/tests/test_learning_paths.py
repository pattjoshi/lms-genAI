"""Phase 3b learning paths: finding the concept and ordering the steps. No database needed."""

from app.graph.paths import Candidate, match_by_embedding, match_by_rules, study_order

CANDIDATES = [
    Candidate("3:backpropagation", "Backpropagation", 3, aliases=["Backprop"], embedding=[1.0, 0.0]),
    Candidate("3:chain rule", "Chain Rule", 3, embedding=[0.0, 1.0]),
    Candidate("3:gradient descent", "Gradient Descent", 3, embedding=[0.6, 0.8]),
]


def test_rules_find_names_aliases_and_partial_names():
    assert match_by_rules("backprop", CANDIDATES)[0] == (CANDIDATES[0], 1.0)  # alias
    assert match_by_rules("the chain rules", CANDIDATES)[0] == (CANDIDATES[1], 1.0)  # same key
    assert match_by_rules("gradient", CANDIDATES)[0][0].name == "Gradient Descent"  # contained
    assert match_by_rules("stochastic gradient descent", CANDIDATES)[0][0].name == "Gradient Descent"
    assert match_by_rules("why is my loss exploding", CANDIDATES) == []  # rules give up -> embeddings
    assert match_by_rules("   ", CANDIDATES) == []


def test_embedding_fallback_respects_the_threshold():
    hits = match_by_embedding([0.1, 0.99], CANDIDATES, min_similarity=0.5)
    assert [c.name for c, _ in hits] == ["Chain Rule", "Gradient Descent"]
    assert match_by_embedding([-1.0, 0.0], CANDIDATES, min_similarity=0.5) == []


def test_study_order_puts_prerequisites_first_and_breaks_ties_in_course_order():
    # backprop needs chain rule + gradient descent; chain rule needs derivatives
    uids = ["backprop", "chain", "gd", "deriv"]
    edges = [("backprop", "chain"), ("backprop", "gd"), ("chain", "deriv")]
    rank = {"deriv": (1, 0), "chain": (1, 5), "gd": (2, 0), "backprop": (2, 3)}
    order = study_order(uids, edges, rank)
    assert order == ["deriv", "chain", "gd", "backprop"]
    # gradient descent earlier in the course than derivatives -> it may come first (it is ready too)
    rank["gd"] = (0, 0)
    assert study_order(uids, edges, rank) == ["gd", "deriv", "chain", "backprop"]


def test_study_order_survives_a_cycle():
    order = study_order(["a", "b", "c"], [("a", "b"), ("b", "a"), ("a", "c")], {})
    assert sorted(order) == ["a", "b", "c"]
    assert order[0] == "c"
