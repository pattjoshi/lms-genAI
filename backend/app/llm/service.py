"""The one door to the chat LLM.

Every feature (hello test now; doubt answering, extraction, SQL... later) calls
`chat()`. It runs the same safety steps every time:

    1. circuit breaker open?      -> refuse fast
    2. daily budget used up?      -> refuse
    3. call OpenAI via LangChain  -> retry temporary errors (max LLM_MAX_RETRIES)
    4. record tokens/cost/latency -> llm_usage table (success AND failure)
    5. Langfuse trace             -> attached through the LangChain callback

`chat_stream()` does the same for token-by-token answers, `embed_texts()` for
embeddings (Phase 1), and `chat_structured()` for answers that must be JSON (Phase 3).
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pydantic import BaseModel
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


def build_chat_model(
    settings: Settings, max_tokens: int | None = None, streaming: bool = False, model: str | None = None
) -> ChatOpenAI:
    """`model` overrides OPENAI_CHAT_MODEL for one call (Phase 7: the eval's judge)."""
    _require_key(settings)
    kwargs = {}
    if streaming:
        kwargs["stream_usage"] = True  # OpenAI then sends token counts in the last streamed chunk
    if settings.openai_temperature is not None:
        kwargs["temperature"] = settings.openai_temperature
    return ChatOpenAI(
        model=model or settings.openai_chat_model,
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
    model = build_chat_model(get_settings(), max_tokens)
    response, result = await _invoke(session, model, messages, feature, user, session_id, raw=lambda r: r)
    result.text = str(response.content)
    return result


async def chat_structured[T: BaseModel](
    session: AsyncSession,
    *,
    messages: list[BaseMessage],
    schema: type[T],
    feature: str,
    user: User | None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> tuple[T, LLMResult]:
    """Like chat(), but the answer is an object of `schema` instead of free text (Phase 3).

    OpenAI's "structured outputs" (json_schema, strict) constrains the model's decoding to
    the JSON schema generated from the pydantic class, so the JSON always parses and has
    every field. It does NOT make the content correct: callers still check the values
    (e.g. that a quoted sentence really is in the source text).

    `model` (Phase 7) runs this one call on another model, e.g. a stronger judge for the eval.
    Its cost is estimated with the chat model's prices.
    """
    runnable = build_chat_model(get_settings(), max_tokens, model=model).with_structured_output(
        schema, method="json_schema", strict=True, include_raw=True
    )
    out, result = await _invoke(
        session, runnable, messages, feature, user, None, raw=lambda r: r["raw"], model_name=model
    )
    if out["parsed"] is None:
        # Only happens when the output was cut off (max_tokens) or the model refused.
        raise LLMUnavailableError(
            "The AI returned an incomplete answer. Please try again.",
            code="bad_structured_output",
            detail=repr(out.get("parsing_error")),
        )
    result.text = out["raw"].content if isinstance(out["raw"].content, str) else ""
    return out["parsed"], result


async def chat_with_tools(
    session: AsyncSession,
    *,
    messages: list[BaseMessage],
    tools: list,
    feature: str,
    user: User | None,
    max_tokens: int | None = None,
    tool_choice: str | None = None,
) -> tuple[AIMessage, LLMResult]:
    """One step of a tool-calling loop (Phase 4b): the model either asks for tool calls
    (`message.tool_calls`) or answers in `message.content`. Same gateway as chat(): budget,
    retries, usage row, trace. The loop itself, and running the tools, is the caller's job."""
    model = build_chat_model(get_settings(), max_tokens).bind_tools(tools, tool_choice=tool_choice)
    response, result = await _invoke(session, model, messages, feature, user, None, raw=lambda r: r)
    result.text = response.content if isinstance(response.content, str) else ""
    return response, result


async def _invoke(session, runnable, messages, feature, user, session_id, *, raw, model_name=None) -> tuple:
    """Steps 1-5 of the module docstring around one call. `raw(response)` returns the
    AIMessage, which carries the token usage."""
    settings = get_settings()
    model_name = model_name or settings.openai_chat_model
    openai_breaker.before_call()
    await ensure_budget_available(session, settings)

    config = {
        "callbacks": langfuse_callbacks(settings),
        "metadata": trace_metadata(user, feature, session_id),
        "run_name": feature,
    }

    started = time.perf_counter()
    try:
        response, attempts = await call_with_retry(
            lambda: runnable.ainvoke(messages, config=config),
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
            model=model_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
            attempts=err.attempts,
            status="error",
            error_code=err.code,
        )
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = raw(response).usage_metadata or {}
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    cost = chat_cost_usd(input_tokens, output_tokens, settings)

    await record_usage(
        session,
        user_id=user.id if user else None,
        feature=feature,
        model=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        attempts=attempts,
        status="success",
    )
    return response, LLMResult(
        text="",
        model=model_name,
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
