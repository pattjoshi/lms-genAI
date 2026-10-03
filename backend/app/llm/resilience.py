"""Retry with exponential backoff + a circuit breaker.

Retry: for TEMPORARY errors only, wait 1s, 2s, 4s (plus a little random "jitter" so
many clients don't retry at the same instant), then give up.

Circuit breaker: if the last N calls all failed, stop calling OpenAI for a cooldown
period. It protects your money and OpenAI's servers when something is clearly broken.

    CLOSED  --N failures-->  OPEN  --cooldown passed-->  HALF_OPEN
      ^                                                      |
      +------------------ trial call succeeds ---------------+
                          (trial fails -> back to OPEN)
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum

from app.llm.errors import (
    CircuitOpenError,
    ErrorKind,
    LLMConfigError,
    LLMUnavailableError,
    classify,
)

log = logging.getLogger(__name__)


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> BreakerState:
        if self._opened_at is None:
            return BreakerState.CLOSED
        if self._clock() - self._opened_at >= self.cooldown_seconds:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def before_call(self) -> None:
        if self.state == BreakerState.OPEN:
            wait = self.cooldown_seconds - (self._clock() - self._opened_at)
            raise CircuitOpenError(
                f"AI calls are paused for {wait:.0f}s after repeated failures. Please try again shortly.",
                code="ai_paused",
            )

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        if self.state == BreakerState.HALF_OPEN:
            # The trial call failed: open again for a full cooldown.
            self._opened_at = self._clock()
            log.warning("Circuit breaker trial call failed; re-opening.")
            return
        self._failures += 1
        if self._failures >= self.failure_threshold and self._opened_at is None:
            self._opened_at = self._clock()
            log.warning("Circuit breaker OPEN after %d consecutive failures.", self._failures)


def backoff_delay(attempt: int, base: float, maximum: float, jitter: bool = True) -> float:
    """attempt=1 -> base, 2 -> 2*base, 3 -> 4*base ... capped at `maximum`."""
    delay = min(base * (2 ** (attempt - 1)), maximum)
    if jitter:
        delay += random.uniform(0, base * 0.25)
    return delay


def _retry_after_seconds(exc: BaseException) -> float | None:
    """OpenAI sometimes tells us exactly how long to wait (Retry-After header)."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


async def call_with_retry[T](
    fn: Callable[[], Awaitable[T]],
    *,
    breaker: CircuitBreaker,
    max_retries: int,
    base_delay: float,
    max_delay: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter: bool = True,
) -> tuple[T, int]:
    """Run `fn`, retrying TEMPORARY errors. Returns (result, attempts_used)."""
    attempt = 0
    while True:
        attempt += 1
        breaker.before_call()  # also stops a retry loop if the breaker opened meanwhile
        try:
            result = await fn()
        except Exception as exc:  # noqa: BLE001 - we classify everything
            info = classify(exc)
            if info.trips_breaker:
                breaker.record_failure()
            detail = f"{type(exc).__name__}: {exc}"

            if info.kind == ErrorKind.PERMANENT:
                log.error("LLM call failed permanently (%s): %s", info.code, detail)
                raise LLMConfigError(info.user_message, code=info.code, detail=detail, attempts=attempt) from exc

            if attempt > max_retries:
                log.error("LLM call still failing after %d attempts (%s): %s", attempt, info.code, detail)
                raise LLMUnavailableError(
                    f"{info.user_message} Tried {attempt} times. Please try again in a minute.",
                    code=info.code,
                    detail=detail,
                    attempts=attempt,
                ) from exc

            breaker.before_call()  # breaker just opened? stop now instead of sleeping first
            delay = backoff_delay(attempt, base_delay, max_delay, jitter)
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                delay = min(max(delay, retry_after), max_delay)
            log.warning("LLM temporary error (%s), retry %d/%d in %.1fs", info.code, attempt, max_retries, delay)
            await sleep(delay)
        else:
            breaker.record_success()
            return result, attempt
