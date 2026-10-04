"""Phase 2 retrieval steps, each tested on its own. No Qdrant, OpenAI or model download needed."""

import pytest

from app.evals.retrieval import ModeResult
from app.prompts.rewrite import format_history
from app.rag import reranker, sparse
from app.rag.fusion import rrf
from app.rag.retriever import Candidate, fuse, mark_used
from app.rag.rewrite import clean, same_text
from app.rag.vectorstore import Hit
from app.routers.chat import AskIn

# ---------- BM25 sparse vectors ----------


def test_tokenize_keeps_code_tokens_and_their_parts():
    tokens = sparse.tokenize("Using pd.merge for JOINS in k-means and __init__")
    assert "pd.merge" in tokens and "pd" in tokens and "merg" in tokens  # compound + parts (stemmed)
    assert "join" in tokens  # "JOINS" -> lower case + stem
    assert "k-means" in tokens and "mean" in tokens
    assert "__init__" in tokens  # code is not stemmed
    assert "for" not in tokens and "and" not in tokens  # stop words removed


def test_token_ids_are_stable():
    # crc32, not Python's hash(): the same word must get the same id in every process, forever.
    assert sparse.token_id("relu") == sparse.token_id("relu") == 1195974616


def test_bm25_term_frequency_saturates_and_long_chunks_are_penalised():
    once = sparse.encode_document("index")
    twice = sparse.encode_document("index index")
    assert twice.values[0] > once.values[0]
    assert twice.values[0] < 2 * once.values[0]  # diminishing returns (k1)
    long = sparse.encode_document("index " + " ".join(f"word{i}" for i in range(300)))
    idx = long.indices.index(sparse.token_id("index"))
    assert long.values[idx] < once.values[0]  # same tf in a longer chunk weighs less (b)


def test_query_vector_has_weight_one_per_distinct_token():
    q = sparse.encode_query("ReLU relu dying ReLU")
    assert sorted(q.values) == [1.0, 1.0]
    assert not sparse.encode_query("what is the")  # only stop words -> empty -> keyword search skipped


# ---------- Fusion ----------


def test_rrf_rewards_agreement_between_lists():
    fused = dict(rrf([["a", "b", "c"], ["b", "d"]], k=60))
    assert max(fused, key=fused.get) == "b"  # 2nd + 1st beats 1st in only one list
    assert fused["a"] > fused["d"]  # rank 1 in one list beats rank 2 in one list


def test_fuse_records_both_ranks():
    dense = [Hit("a", 0.8, {}), Hit("b", 0.7, {})]
    keyword = [Hit("c", 9.0, {}), Hit("a", 5.0, {})]
    cands = fuse(dense, keyword, hybrid=True, rrf_k=60)
    by_id = {c.hit_id: c for c in cands}
    assert cands[0].hit_id == "a"  # found by both
    assert by_id["a"].dense_rank == 1 and by_id["a"].keyword_rank == 2
    assert by_id["c"].cosine is None and by_id["c"].keyword_rank == 1
    assert [c.hit_id for c in fuse(dense, [], hybrid=False, rrf_k=60)] == ["a", "b"]  # Phase 1 order


# ---------- Relevance gate ----------


def test_mark_used_with_reranker_trusts_rerank_score():
    cands = [Candidate("a", {}, cosine=0.1, rerank=0.9), Candidate("b", {}, cosine=0.9, rerank=0.001)]
    mark_used(cands, reranked=True, best_cosine=0.9, min_score=0.25, min_rerank_score=0.02)
    assert [c.used for c in cands] == [True, False]


def test_mark_used_without_reranker_uses_cosine_and_guards_keyword_only_hits():
    cands = [Candidate("a", {}, cosine=0.5), Candidate("b", {}, cosine=0.1), Candidate("c", {})]
    mark_used(cands, reranked=False, best_cosine=0.5, min_score=0.25, min_rerank_score=0.02)
    assert [c.used for c in cands] == [True, False, True]
    # Off-topic question: a keyword-only hit must not sneak in.
    off = [Candidate("c", {}), Candidate("d", {}, cosine=0.1)]
    mark_used(off, reranked=False, best_cosine=0.1, min_score=0.25, min_rerank_score=0.02)
    assert not any(c.used for c in off)


# ---------- Rewrite helpers ----------


def test_clean_rewrite_output():
    assert clean('"What is the chain rule?"', "x") == "What is the chain rule?"
    assert clean("Standalone question: Give an example of ReLU\nExtra line", "x") == "Give an example of ReLU"
    assert clean("   \n  ", "fallback") == "fallback"
    assert same_text("What is ReLU?", "what is  relu")


def test_history_is_short():
    text = format_history([("What is a join?", "word " * 200)])
    assert text.startswith("Student: What is a join?\nAssistant: ")
    assert len(text) < 360 and text.endswith("...")


def test_conversation_id_is_validated():
    assert AskIn(question="why?", conversation_id="3f2a-11").conversation_id == "3f2a-11"
    with pytest.raises(ValueError):
        AskIn(question="why?", conversation_id="<script>")


# ---------- Reranker (fake model, no download) ----------


class FakeCrossEncoder:
    def rerank(self, query, texts, batch_size=32):
        words = set(query.lower().split())
        return [4.0 if words & set(t.lower().split()) else -6.0 for t in texts]


async def test_reranker_scores_are_probabilities(monkeypatch):
    monkeypatch.setattr(reranker, "_model", FakeCrossEncoder())
    scores = await reranker.score("dying relu", ["Dying ReLU stops learning", "B-tree index"])
    assert scores[0] > 0.9 and scores[1] < 0.01


async def test_reranker_unavailable_is_reported_not_retried_every_time(monkeypatch):
    monkeypatch.setattr(reranker, "_model", None)
    monkeypatch.setattr(reranker, "_failed_at", None)
    calls = []

    def boom(**_kwargs):
        calls.append(1)
        raise OSError("no internet")

    import fastembed.rerank.cross_encoder as ce

    monkeypatch.setattr(ce, "TextCrossEncoder", boom)
    for _ in range(3):
        with pytest.raises(reranker.RerankerUnavailable):
            await reranker.score("q", ["t"])
    assert len(calls) == 1  # waits RETRY_LOAD_AFTER_S before trying to load again
    monkeypatch.setattr(reranker, "_failed_at", None)


# ---------- Eval metrics ----------


def test_mode_result_metrics_by_category():
    r = ModeResult(mode="x", k=5)
    r.ranks = {"a": 1, "b": 3, "c": None, "d": 2}
    r.categories = {"a": "semantic", "b": "semantic", "c": "keyword", "d": "keyword"}
    assert r.hit(1) == 0.25 and r.hit(3) == 0.75
    assert r.hit(5, "keyword") == 0.5
    assert r.mrr() == pytest.approx((1 + 1 / 3 + 0 + 1 / 2) / 4)
