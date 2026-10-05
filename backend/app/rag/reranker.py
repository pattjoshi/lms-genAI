"""Reranking with a cross-encoder that runs locally (CPU, ONNX via fastembed).

Retrieval so far used a BI-encoder: the question and each chunk were embedded
separately, then compared. That is fast (chunk vectors are computed once, at upload)
but the model never sees the question and the chunk together.

A CROSS-encoder reads "question + chunk" as one input and outputs how relevant the chunk
is. It is much more accurate, but must run once per (question, chunk) pair at question
time, so we only use it on the ~20 candidates the fast search returned:

    fast search (all chunks) -> 20 candidates -> cross-encoder -> best 5

Model: ms-marco-MiniLM-L-6-v2 (~80 MB), trained on Bing search queries. It is downloaded
once into storage/models/. If it can't be loaded (no internet on first run, disk full...)
retrieval keeps working without reranking: a feature should degrade, not break answers.
"""

import asyncio
import logging
import math
import threading
import time

from app.config import get_settings

log = logging.getLogger(__name__)

RETRY_LOAD_AFTER_S = 300  # after a failed load, don't retry on every question

_model = None
_failed_at: float | None = None
_failure: str = ""
_lock = threading.Lock()


class RerankerUnavailable(Exception):
    pass


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(min(x, 50), -50)))


def _load():
    global _model, _failed_at, _failure
    with _lock:
        if _model is not None:
            return _model
        if _failed_at is not None and time.monotonic() - _failed_at < RETRY_LOAD_AFTER_S:
            raise RerankerUnavailable(_failure)
        s = get_settings()
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            s.model_cache_dir.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            _model = TextCrossEncoder(model_name=s.reranker_model, cache_dir=str(s.model_cache_dir))
            log.info("Loaded reranker %s in %.1fs", s.reranker_model, time.perf_counter() - started)
            _failed_at = None
            return _model
        except Exception as exc:  # noqa: BLE001 - any load problem means "run without reranking"
            _failed_at = time.monotonic()
            _failure = f"Reranker model could not be loaded ({type(exc).__name__}: {str(exc)[:200]})"
            log.warning("%s. Answers still work, without reranking.", _failure)
            raise RerankerUnavailable(_failure) from exc


def _score_sync(query: str, texts: list[str]) -> list[float]:
    model = _load()
    # The model outputs a raw score (a logit, roughly -12..+12). The sigmoid turns it into
    # 0..1, which is easier to read and to put a threshold on.
    return [round(_sigmoid(float(x)), 4) for x in model.rerank(query, texts, batch_size=32)]


async def score(query: str, texts: list[str]) -> list[float]:
    """Relevance (0..1) of each text to the query. Raises RerankerUnavailable."""
    if not texts:
        return []
    # CPU-heavy work runs in a thread so the server keeps serving other requests.
    return await asyncio.to_thread(_score_sync, query, texts)


async def warm_up() -> None:
    """Load (and on first run download) the model at startup, so the first question isn't slow."""
    try:
        await asyncio.to_thread(_load)
    except RerankerUnavailable:
        pass


def status() -> str:
    if _model is not None:
        return "ready"
    return "unavailable" if _failed_at is not None else "not loaded"
