"""The one door to the chat LLM.

Every feature (hello test now; doubt answering, extraction, SQL... later) calls
`chat()`. It runs the same safety steps every time:

    1. circuit breaker open?      -> refuse fast
    2. daily budget used up?      -> refuse
    3. call OpenAI via LangChain  -> retry temporary errors (max LLM_MAX_RETRIES)
    4. record tokens/cost/latency -> llm_usage table (success AND failure)
    5. Langfuse trace             -> attached through the LangChain callback

`chat_stream()` does the same for token-by-token answers, and `embed_texts()` for
embeddings (Phase 1).
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.llm.budget import chat_cost_usd, embedding_cost_usd, ensure_budget_available, record_usage
from app.llm.errors import LLMConfigError, LLMError, LLMUnavailableError, classify
from app.llm.resilience import CircuitBreaker, call_with_retry
from app.llm.tracing import langfuse_callbacks, observe, trace_metadata
from app.models import User

_settings = get_settings()

# One breaker for the whole process: if OpenAI is down, it's down for everyone.
openai_breaker = CircuitBreaker(
    failure_threshold=_settings.circuit_breaker_failure_threshold,
    cooldown_seconds=_settings.circuit_breaker_cooldown_seconds,
)


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    attempts: int


def _require_key(settings: Settings) -> None:
    if settings.openai_api_key is None:
        raise LLMConfigError(
            "OPENAI_API_KEY is not set. Add it to the .env file and restart the backend.",
            code="missing_api_key",
        )


def build_chat_model(settings: Settings, max_tokens: int | None = None, streaming: bool = False) -> ChatOpenAI:
    _require_key(settings)
    kwargs = {}
    if streaming:
        kwargs["stream_usage"] = True  # OpenAI then sends token counts in the last streamed chunk
    if settings.openai_temperature is not None:
        kwargs["temperature"] = settings.openai_temperature
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.llm_timeout_seconds,
        max_tokens=max_tokens or settings.llm_max_output_tokens,
        # Retries are OUR job (see resilience.py) so we can classify errors and log them.
        # Leaving the SDK's own retries on would multiply the attempts.
        max_retries=0,
        **kwargs,
    )


async def chat(
    session: AsyncSession,
    *,
    messages: list[BaseMessage],
    feature: str,
    user: User | None,
    max_tokens: int | None = None,
    session_id: str | None = None,
) -> LLMResult:
    settings = get_settings()
    openai_breaker.before_call()
    await ensure_budget_available(session, settings)
    model = build_chat_model(settings, max_tokens)

    config = {
        "callbacks": langfuse_callbacks(settings),
        "metadata": trace_metadata(user, feature, session_id),
        "run_name": feature,
    }

    started = time.perf_counter()
    try:
        response, attempts = await call_with_retry(
            lambda: model.ainvoke(messages, config=config),
            breaker=openai_breaker,
            max_retries=settings.llm_max_retries,
            base_delay=settings.llm_retry_base_delay_seconds,
            max_delay=settings.llm_retry_max_delay_seconds,
        )
    except LLMError as err:
        await record_usage(
            session,
            user_id=user.id if user else None,
            feature=feature,
            model=settings.openai_chat_model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            attempts=err.attempts,
            status="error",
            error_code=err.code,
        )
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = response.usage_metadata or {}
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    cost = chat_cost_usd(input_tokens, output_tokens, settings)

    await record_usage(
        session,
        user_id=user.id if user else None,
        feature=feature,
        model=settings.openai_chat_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        attempts=attempts,
        status="success",
    )
    return LLMResult(
        text=str(response.content),
        model=settings.openai_chat_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        attempts=attempts,
    )


# ---------------------------------------------------------------------------
# Streaming (Phase 1): tokens are sent to the browser as soon as they arrive.
# ---------------------------------------------------------------------------


@dataclass
class StreamStats:
    """Filled in by chat_stream() while it runs; read it after the stream ends."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    first_token_ms: int = 0  # "time to first token": what the user perceives as speed
    attempts: int = 0


async def chat_stream(
    session: AsyncSession,
    *,
    messages: list[BaseMessage],
    feature: str,
    user: User | None,
    stats: StreamStats,
    max_tokens: int | None = None,
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """Yield text pieces as the model produces them.

    Retry rule for streams: we can retry only until the FIRST piece arrives. After that
    the user has already seen part of the answer, so a failure ends the stream with an
    error instead of silently starting over.
    """
    settings = get_settings()
    openai_breaker.before_call()
    await ensure_budget_available(session, settings)
    model = build_chat_model(settings, max_tokens, streaming=True)
    stats.model = settings.openai_chat_model
    config = {
        "callbacks": langfuse_callbacks(settings),
        "metadata": trace_metadata(user, feature, session_id),
        "run_name": feature,
    }

    async def open_stream():
        stream = model.astream(messages, config=config)
        first = await anext(stream, None)
        if first is None:
            raise LLMUnavailableError("The AI returned an empty response.", code="empty_response")
        return stream, first

    started = time.perf_counter()

    async def record_error(code: str, attempts: int) -> None:
        await record_usage(
            session,
            user_id=user.id if user else None,
            feature=feature,
            model=settings.openai_chat_model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            attempts=attempts,
            status="error",
            error_code=code,
        )

    try:
        (stream, full), attempts = await call_with_retry(
            open_stream,
            breaker=openai_breaker,
            max_retries=settings.llm_max_retries,
            base_delay=settings.llm_retry_base_delay_seconds,
            max_delay=settings.llm_retry_max_delay_seconds,
        )
    except LLMError as err:
        await record_error(err.code, err.attempts)
        raise

    stats.attempts = attempts
    stats.first_token_ms = int((time.perf_counter() - started) * 1000)
    if full.content:
        yield str(full.content)
    try:
        async for chunk in stream:
            full = full + chunk  # merges text AND usage metadata
            if chunk.content:
                yield str(chunk.content)
    except Exception as exc:  # noqa: BLE001
        if classify(exc).trips_breaker:
            openai_breaker.record_failure()
        await record_error("stream_interrupted", attempts)
        raise LLMUnavailableError(
            "The answer was interrupted. Please ask again.",
            code="stream_interrupted",
            detail=f"{exc!r}",
            attempts=attempts,
        ) from exc

    usage = full.usage_metadata or {}
    stats.input_tokens = int(usage.get("input_tokens", 0))
    stats.output_tokens = int(usage.get("output_tokens", 0))
    stats.cost_usd = chat_cost_usd(stats.input_tokens, stats.output_tokens, settings)
    stats.latency_ms = int((time.perf_counter() - started) * 1000)
    await record_usage(
        session,
        user_id=user.id if user else None,
        feature=feature,
        model=settings.openai_chat_model,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        cost_usd=stats.cost_usd,
        latency_ms=stats.latency_ms,
        attempts=attempts,
        status="success",
    )


# ---------------------------------------------------------------------------
# Embeddings (Phase 1): text -> vector, with the same safety steps as chat.
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingResult:
    vectors: list[list[float]] = field(default_factory=list)
    tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 0


async def embed_texts(session: AsyncSession, texts: list[str], *, feature: str, user: User | None) -> EmbeddingResult:
    """Embed many texts, in batches of EMBEDDING_BATCH_SIZE per API request.

    We call the OpenAI SDK directly (not LangChain) because its response includes the
    exact token count, which we need for cost tracking.
    """
    settings = get_settings()
    result = EmbeddingResult()
    if not texts:
        return result
    _require_key(settings)
    openai_breaker.before_call()
    await ensure_budget_available(session, settings)

    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.openai_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,
    )
    started = time.perf_counter()
    with observe(
        feature, as_type="embedding", model=settings.openai_embedding_model, input={"texts": len(texts)}
    ) as span:
        try:
            for start in range(0, len(texts), settings.embedding_batch_size):
                batch = texts[start : start + settings.embedding_batch_size]
                response, attempts = await call_with_retry(
                    lambda b=batch: client.embeddings.create(model=settings.openai_embedding_model, input=b),
                    breaker=openai_breaker,
                    max_retries=settings.llm_max_retries,
                    base_delay=settings.llm_retry_base_delay_seconds,
                    max_delay=settings.llm_retry_max_delay_seconds,
                )
                result.attempts += attempts
                result.vectors += [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
                result.tokens += response.usage.total_tokens
        except LLMError as err:
            await record_usage(
                session,
                user_id=user.id if user else None,
                feature=feature,
                model=settings.openai_embedding_model,
                input_tokens=result.tokens,
                cost_usd=embedding_cost_usd(result.tokens, settings),
                latency_ms=int((time.perf_counter() - started) * 1000),
                attempts=max(err.attempts, 1),
                status="error",
                error_code=err.code,
            )
            raise
        finally:
            await client.close()

        result.cost_usd = embedding_cost_usd(result.tokens, settings)
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        span.update(usage_details={"input": result.tokens}, cost_details={"total": result.cost_usd})

    await record_usage(
        session,
        user_id=user.id if user else None,
        feature=feature,
        model=settings.openai_embedding_model,
        input_tokens=result.tokens,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        attempts=result.attempts,
        status="success",
    )
    return result
