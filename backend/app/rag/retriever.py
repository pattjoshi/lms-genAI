"""Query pipeline, retrieval half. Phase 2 turns one vector search into a small pipeline:

    question
      -> 1. rewrite follow-up into a standalone question   (LLM, only when there is chat history)
      -> 2. search: meaning (dense) + keywords (BM25)       (one Qdrant request, pre-filtered)
      -> 3. fuse the two rankings with RRF                  (fusion.py)
      -> 4. rerank the ~20 candidates with a cross-encoder  (reranker.py, local CPU)
      -> 5. keep the best RAG_TOP_K, mark which are relevant enough to use
      -> 6. nothing relevant? rewrite into textbook terms and search once more (corrective)

Every step can be switched off (RetrievalOptions / .env), which is how the eval measures
what each one adds. With everything off it is exactly Phase 1: top-k cosine search.

Security note: the course filter comes from the user's identity (permission matrix),
NEVER from the question or the LLM. A student can only ever retrieve chunks of courses
they are enrolled in, whatever they type. A course/module chosen in the UI can only
NARROW that set.
"""

import time
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.errors import LLMError
from app.llm.service import embed_texts
from app.llm.tracing import observe
from app.models import Module, User
from app.rag import reranker, rewrite, sparse, vectorstore
from app.rag.fusion import rrf
from app.scopes import readable_course_ids


@dataclass(frozen=True)
class RetrievalOptions:
    hybrid: bool = True
    rerank: bool = True
    rewrite: bool = True
    corrective: bool = True

    @classmethod
    def from_settings(cls) -> "RetrievalOptions":
        s = get_settings()
        return cls(hybrid=s.rag_hybrid, rerank=s.rag_rerank, rewrite=s.rag_rewrite, corrective=s.rag_corrective)

    @classmethod
    def baseline(cls) -> "RetrievalOptions":
        """Phase 1 behaviour: dense search only."""
        return cls(hybrid=False, rerank=False, rewrite=False, corrective=False)


@dataclass
class Candidate:
    hit_id: str
    payload: dict
    cosine: float | None = None  # None = found only by keyword search
    dense_rank: int | None = None
    keyword_rank: int | None = None
    rrf: float | None = None
    rerank: float | None = None
    used: bool = False


@dataclass
class SearchResult:
    candidates: list[Candidate] = field(default_factory=list)  # final order, cut to top_k
    best_cosine: float | None = None
    reranked: bool = False
    rerank_error: str | None = None
    embed_tokens: int = 0
    embed_cost_usd: float = 0.0
    timings_ms: dict = field(default_factory=dict)

    @property
    def has_context(self) -> bool:
        return any(c.used for c in self.candidates)


@dataclass
class Retrieval:
    question: str
    query: str = ""  # the text actually searched
    rewritten: bool = False  # query came from the follow-up rewrite
    retried_with: str | None = None  # corrective retry query that produced the result
    retry_tried: str | None = None  # corrective retry query (even if it found nothing better)
    options: RetrievalOptions = field(default_factory=RetrievalOptions)
    course_ids: list[int] = field(default_factory=list)
    module_id: int | None = None
    search: SearchResult = field(default_factory=SearchResult)
    sources: list[dict] = field(default_factory=list)  # ranked, best first
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost_usd: float = 0.0
    embed_tokens: int = 0
    embed_cost_usd: float = 0.0
    timings_ms: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_context(self) -> bool:
        return any(s["used"] for s in self.sources)

    @property
    def top_score(self) -> float | None:
        """Best cosine similarity of the search (Phase 1's relevance signal)."""
        return self.search.best_cosine

    @property
    def top_rerank_score(self) -> float | None:
        scores = [s["rerank_score"] for s in self.sources if s.get("rerank_score") is not None]
        return max(scores) if scores else None

    @property
    def cost_usd(self) -> float:
        return self.embed_cost_usd + self.llm_cost_usd

    def relevance(self) -> dict:
        """Which signal decided 'relevant or not', for the UI and the doubt log."""
        s = get_settings()
        if self.search.reranked:
            return {"by": "rerank", "best": self.top_rerank_score, "threshold": s.rag_min_rerank_score}
        return {"by": "cosine", "best": self.top_score, "threshold": s.rag_min_score}

    def details(self) -> dict:
        """'How this answer was found' panel."""
        return {
            "question": self.question,
            "query": self.query,
            "rewritten": self.rewritten,
            "retried_with": self.retried_with,
            "retry_tried": self.retry_tried,
            "hybrid": self.options.hybrid,
            "rerank": self.options.rerank,
            "reranked": self.search.reranked,
            "rerank_error": self.search.rerank_error,
            "rewrite": self.options.rewrite,
            "corrective": self.options.corrective,
            "course_ids": self.course_ids,
            "module_id": self.module_id,
            "relevance": self.relevance(),
            "timings_ms": self.timings_ms,
            "llm_cost_usd": self.llm_cost_usd,
            "warnings": self.warnings,
        }


def mark_used(
    candidates: list[Candidate],
    *,
    reranked: bool,
    best_cosine: float | None,
    min_score: float,
    min_rerank_score: float,
) -> None:
    """Decide which chunks are relevant enough to give to the LLM.

    - Reranked: the cross-encoder read question + chunk together; trust its score.
    - Not reranked: Phase 1 rule, cosine >= RAG_MIN_SCORE. A chunk found only by keyword
      search has no cosine; it is used when the question as a whole is on-topic (the best
      meaning match passes), so keyword hits can't sneak in for an off-topic question.
    """
    question_on_topic = best_cosine is not None and best_cosine >= min_score
    for c in candidates:
        if reranked:
            c.used = c.rerank is not None and c.rerank >= min_rerank_score
        elif c.cosine is not None:
            c.used = c.cosine >= min_score
        else:
            c.used = question_on_topic


def fuse(dense: list[vectorstore.Hit], keyword: list[vectorstore.Hit], hybrid: bool, rrf_k: int) -> list[Candidate]:
    """Merge the two hit lists into candidates, best first (RRF when hybrid)."""
    by_id: dict[str, Candidate] = {}
    for rank, hit in enumerate(dense, start=1):
        by_id[hit.id] = Candidate(hit.id, hit.payload, cosine=round(hit.score, 4), dense_rank=rank)
    for rank, hit in enumerate(keyword, start=1):
        c = by_id.setdefault(hit.id, Candidate(hit.id, hit.payload))
        c.keyword_rank = rank
    if not hybrid:
        return list(by_id.values())
    order = rrf([[h.id for h in dense], [h.id for h in keyword]], k=rrf_k)
    out = []
    for hit_id, score in order:
        by_id[hit_id].rrf = round(score, 5)
        out.append(by_id[hit_id])
    return out


async def _search(
    session: AsyncSession,
    user: User,
    query: str,
    course_ids: list[int],
    module_id: int | None,
    top_k: int,
    opts: RetrievalOptions,
) -> SearchResult:
    s = get_settings()
    result = SearchResult()

    started = time.perf_counter()
    embedded = await embed_texts(session, [query], feature="rag_embed_query", user=user)
    result.embed_tokens, result.embed_cost_usd = embedded.tokens, embedded.cost_usd
    result.timings_ms["embed"] = _ms(started)

    # Fetch more than top_k when a later step (fusion / reranking) will choose among them.
    limit = s.rag_candidates if (opts.hybrid or opts.rerank) else top_k
    started = time.perf_counter()
    keywords = sparse.encode_query(query) if opts.hybrid else None
    dense_hits, keyword_hits = await vectorstore.search(embedded.vectors[0], keywords, course_ids, limit, module_id)
    result.timings_ms["search"] = _ms(started)
    result.best_cosine = round(dense_hits[0].score, 4) if dense_hits else None

    candidates = fuse(dense_hits, keyword_hits, opts.hybrid, s.rag_rrf_k)

    if opts.rerank and candidates:
        started = time.perf_counter()
        with observe("rerank", input={"query": query, "candidates": len(candidates)}) as span:
            try:
                scores = await reranker.score(query, [c.payload.get("text", "") for c in candidates])
                for c, score in zip(candidates, scores, strict=True):
                    c.rerank = score
                candidates.sort(key=lambda c: c.rerank, reverse=True)
                result.reranked = True
                span.update(output=[c.rerank for c in candidates[:top_k]])
            except reranker.RerankerUnavailable as exc:
                result.rerank_error = str(exc)
                span.update(output={"error": str(exc)})
        result.timings_ms["rerank"] = _ms(started)

    result.candidates = candidates[:top_k]
    mark_used(
        result.candidates,
        reranked=result.reranked,
        best_cosine=result.best_cosine,
        min_score=s.rag_min_score,
        min_rerank_score=s.rag_min_rerank_score,
    )
    return result


async def _scope(
    session: AsyncSession, user: User, course_ids: list[int] | None, module_id: int | None
) -> tuple[list[int], int | None]:
    allowed = await readable_course_ids(session, user)
    # An explicit course_ids (UI filter, evals) can only NARROW the allowed set, never widen it.
    scoped = [c for c in course_ids if c in allowed] if course_ids is not None else allowed
    if module_id is not None:
        module = await session.get(Module, module_id)
        # A module implies its course; a module outside the allowed courses gives nothing.
        scoped = [module.course_id] if module is not None and module.course_id in scoped else []
    return scoped, module_id


async def retrieve(
    session: AsyncSession,
    user: User,
    question: str,
    *,
    top_k: int | None = None,
    course_ids: list[int] | None = None,
    module_id: int | None = None,
    history: list[tuple[str, str]] | None = None,
    options: RetrievalOptions | None = None,
) -> Retrieval:
    s = get_settings()
    opts = options or RetrievalOptions.from_settings()
    top_k = top_k or s.rag_top_k
    course_ids, module_id = await _scope(session, user, course_ids, module_id)
    result = Retrieval(question=question, query=question, options=opts, course_ids=course_ids, module_id=module_id)
    if not course_ids:
        return result

    # 1. Follow-up -> standalone question (only when there is something to resolve against)
    if opts.rewrite and history:
        started = time.perf_counter()
        with observe("rewrite_followup", input={"question": question, "turns": len(history)}) as span:
            rw = await _safe_rewrite(result, rewrite.standalone_question(session, user, question, history))
            if rw and rw.changed:
                result.query, result.rewritten = rw.text, True
            span.update(output={"query": result.query})
        result.timings_ms["rewrite"] = _ms(started)

    # 2-5. Search, fuse, rerank, mark relevant
    with observe("search", as_type="retriever", input={"query": result.query}) as span:
        found = await _search(session, user, result.query, course_ids, module_id, top_k, opts)
        span.update(output=_trace_view(found))
    _add_search_costs(result, found)

    # 6. Corrective retry: nothing relevant -> rephrase in textbook terms and search once more
    if opts.corrective and not found.has_context:
        started = time.perf_counter()
        with observe("corrective_retry", input={"query": result.query}) as span:
            rw = await _safe_rewrite(result, rewrite.search_query(session, user, result.query))
            if rw and rw.changed:
                result.retry_tried = rw.text
                second = await _search(session, user, rw.text, course_ids, module_id, top_k, opts)
                _add_search_costs(result, second)
                if second.has_context:
                    found, result.retried_with = second, rw.text
            span.update(output={"retry_query": result.retry_tried, "helped": result.retried_with is not None})
        result.timings_ms["retry"] = _ms(started)

    result.search = found
    result.timings_ms.update({k: v for k, v in found.timings_ms.items() if k not in result.timings_ms})
    result.sources = [_source(rank, c) for rank, c in enumerate(found.candidates, start=1)]
    if found.rerank_error:
        result.warnings.append(found.rerank_error)
    return result


async def _safe_rewrite(result: Retrieval, call) -> rewrite.Rewrite | None:
    """Rewrites are helpers: if the LLM fails, search with what we have instead of failing."""
    try:
        rw = await call
    except LLMError as err:
        result.warnings.append(f"Query rewrite skipped: {err.user_message}")
        return None
    result.llm_input_tokens += rw.input_tokens
    result.llm_output_tokens += rw.output_tokens
    result.llm_cost_usd += rw.cost_usd
    return rw


def _add_search_costs(result: Retrieval, found: SearchResult) -> None:
    result.embed_tokens += found.embed_tokens
    result.embed_cost_usd += found.embed_cost_usd


def _source(rank: int, c: Candidate) -> dict:
    p = c.payload
    return {
        "rank": rank,
        "score": c.cosine,  # cosine similarity (None = found by keyword search only)
        "dense_rank": c.dense_rank,
        "keyword_rank": c.keyword_rank,
        "rrf": c.rrf,
        "rerank_score": c.rerank,
        "used": c.used,  # only these go into the prompt
        "text": p.get("text", ""),
        "file_name": p.get("file_name"),
        "file_type": p.get("file_type"),
        "page": p.get("page"),
        "section": p.get("section"),
        "topic": p.get("topic"),
        "course_code": p.get("course_code"),
        "module_id": p.get("module_id"),
        "document_id": p.get("document_id"),
        "chunk_index": p.get("chunk_index"),
    }


def _trace_view(found: SearchResult) -> list[dict]:
    return [
        {
            "file": c.payload.get("file_name"),
            "topic": c.payload.get("topic"),
            "cosine": c.cosine,
            "dense_rank": c.dense_rank,
            "keyword_rank": c.keyword_rank,
            "rerank": c.rerank,
            "used": c.used,
        }
        for c in found.candidates
    ]


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
