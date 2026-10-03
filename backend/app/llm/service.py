"""The one door to the chat LLM.

Every feature (hello test now; doubt answering, extraction, SQL... later) calls
`chat()`. It runs the same safety steps every time:

    1. circuit breaker open?      -> refuse fast
    2. daily budget used up?      -> refuse
    3. call OpenAI via LangChain  -> retry temporary errors (max LLM_MAX_RETRIES)
    4. record tokens/cost/latency -> llm_usage table (success AND failure)
    5. Langfuse trace             -> attached through the LangChain callback
"""

import time
from dataclasses import dataclass

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.llm.budget import chat_cost_usd, ensure_budget_available, record_usage
from app.llm.errors import LLMConfigError, LLMError
from app.llm.resilience import CircuitBreaker, call_with_retry
from app.llm.tracing import langfuse_callbacks, trace_metadata
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


def build_chat_model(settings: Settings, max_tokens: int | None = None) -> ChatOpenAI:
    if settings.openai_api_key is None:
        raise LLMConfigError(
            "OPENAI_API_KEY is not set. Add it to the .env file and restart the backend.",
            code="missing_api_key",
        )
    kwargs = {}
    if settings.openai_temperature is not None:
        kwargs["temperature"] = settings.openai_temperature
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=settings.openai_api_key,
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
