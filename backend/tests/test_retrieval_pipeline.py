"""retrieve() end to end, with fakes for the database scope, embeddings, Qdrant, reranker and LLM."""

import pytest

from app.llm.errors import LLMUnavailableError
from app.llm.service import EmbeddingResult
from app.models import Module
from app.rag import retriever
from app.rag.retriever import RetrievalOptions, retrieve
from app.rag.rewrite import Rewrite
from app.rag.vectorstore import Hit

GOOD = Hit("good", 0.6, {"text": "Overfitting: the model memorises the training data.", "topic": "Overfitting"})
WEAK = Hit("weak", 0.1, {"text": "Pandas reads CSV files.", "topic": "Pandas Basics"})


class FakeSession:
    async def get(self, model, id_):
        return Module(id=id_, course_id=99) if model is Module else None


@pytest.fixture
def calls(monkeypatch):
    log = {"searched": [], "limits": [], "keywords": []}

    async def readable(_session, _user):
        return [1, 2]

    async def embed(_session, texts, **_kw):
        return EmbeddingResult(vectors=[[0.0] * 3 for _ in texts], tokens=5, cost_usd=0.0000001)

    async def search(_dense, keywords, course_ids, limit, module_id=None):
        log["searched"].append(log["query"])
        log["limits"].append(limit)
        log["keywords"].append(keywords)
        return ([GOOD, WEAK] if "overfit" in log["query"].lower() else [WEAK]), []

    async def score(query, texts):
        return [0.95 if "memorises" in t else 0.001 for t in texts]

    # The fake search can't see the query text, so record it from the embed call.
    async def embed_and_remember(session, texts, **kw):
        log["query"] = texts[0]
        return await embed(session, texts, **kw)

    monkeypatch.setattr(retriever, "readable_course_ids", readable)
    monkeypatch.setattr(retriever, "embed_texts", embed_and_remember)
    monkeypatch.setattr(retriever.vectorstore, "search", search)
    monkeypatch.setattr(retriever.reranker, "score", score)
    return log


def _rewrite_to(text):
    async def fake(*_args, **_kw):
        return Rewrite(text=text, changed=True, input_tokens=50, output_tokens=8, cost_usd=0.00001)

    return fake


async def test_baseline_is_phase_one(calls):
    r = await retrieve(FakeSession(), None, "why does my model overfit?", top_k=5, options=RetrievalOptions.baseline())
    assert calls["limits"] == [5] and calls["keywords"] == [None]  # top_k cosine search, no keywords
    assert [s["used"] for s in r.sources] == [True, False]  # cosine 0.6 passes 0.25, 0.1 doesn't


async def test_reranker_reorders_and_decides_relevance(calls):
    r = await retrieve(
        FakeSession(), None, "why does my model overfit?", options=RetrievalOptions(rewrite=False, corrective=False)
    )
    assert calls["limits"] == [20]  # candidates for the reranker
    assert r.search.reranked and r.sources[0]["rerank_score"] == 0.95
    assert r.relevance()["by"] == "rerank"


async def test_follow_up_is_rewritten_before_searching(calls, monkeypatch):
    monkeypatch.setattr(retriever.rewrite, "standalone_question", _rewrite_to("How do I fix overfitting?"))
    r = await retrieve(FakeSession(), None, "how do I fix it?", history=[("What is overfitting?", "...")])
    assert calls["searched"] == ["How do I fix overfitting?"]
    assert r.rewritten and r.query == "How do I fix overfitting?"
    assert r.llm_cost_usd > 0 and r.has_context


async def test_no_history_means_no_rewrite_call(calls, monkeypatch):
    async def must_not_run(*_a, **_kw):
        raise AssertionError("rewrite called without history")

    monkeypatch.setattr(retriever.rewrite, "standalone_question", must_not_run)
    await retrieve(FakeSession(), None, "what is overfitting?", options=RetrievalOptions(corrective=False))


async def test_corrective_retry_searches_again_with_textbook_terms(calls, monkeypatch):
    monkeypatch.setattr(retriever.rewrite, "search_query", _rewrite_to("overfitting"))
    r = await retrieve(FakeSession(), None, "my model remembers the training data but fails on new data")
    assert len(calls["searched"]) == 2 and calls["searched"][1] == "overfitting"
    assert r.retried_with == "overfitting" and r.has_context
    assert r.embed_tokens == 10  # both searches are paid for and counted


async def test_failed_rewrite_falls_back_to_original_question(calls, monkeypatch):
    async def down(*_a, **_kw):
        raise LLMUnavailableError("OpenAI is not responding.", code="unavailable")

    monkeypatch.setattr(retriever.rewrite, "standalone_question", down)
    r = await retrieve(
        FakeSession(), None, "why overfit?", history=[("q", "a")], options=RetrievalOptions(corrective=False)
    )
    assert calls["searched"] == ["why overfit?"] and not r.rewritten
    assert any("rewrite skipped" in w for w in r.warnings)


async def test_module_filter_cannot_widen_access(calls):
    # Module 7 belongs to course 99, which this user can't read -> nothing is searched.
    r = await retrieve(FakeSession(), None, "anything about overfitting", module_id=7)
    assert r.course_ids == [] and r.sources == [] and calls["searched"] == []
