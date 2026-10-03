"""Retry / stop rules. No real OpenAI calls: we fake the errors."""

import httpx
import openai
import pytest

from app.llm.errors import (
    CircuitOpenError,
    ErrorKind,
    LLMConfigError,
    LLMUnavailableError,
    classify,
)
from app.llm.resilience import BreakerState, CircuitBreaker, backoff_delay, call_with_retry

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _status_error(cls, status: int, body: dict | None = None):
    response = httpx.Response(status, request=REQUEST)
    return cls("error", response=response, body=body)


def test_classify_temporary_errors():
    assert classify(openai.APITimeoutError(request=REQUEST)).kind == ErrorKind.TEMPORARY
    assert classify(openai.APIConnectionError(request=REQUEST)).kind == ErrorKind.TEMPORARY
    assert classify(_status_error(openai.RateLimitError, 429, {"code": "rate_limit_exceeded"})).code == "rate_limited"
    assert classify(_status_error(openai.InternalServerError, 500)).kind == ErrorKind.TEMPORARY


def test_classify_permanent_errors():
    quota = classify(_status_error(openai.RateLimitError, 429, {"code": "insufficient_quota"}))
    assert (quota.kind, quota.code) == (ErrorKind.PERMANENT, "quota_exceeded")
    assert classify(_status_error(openai.AuthenticationError, 401)).code == "invalid_api_key"
    assert classify(_status_error(openai.NotFoundError, 404)).code == "model_not_found"
    assert classify(_status_error(openai.BadRequestError, 400)).code == "bad_request"
    assert classify(ValueError("bug")).kind == ErrorKind.PERMANENT  # unknown -> never retry


def test_backoff_doubles_and_caps():
    assert [backoff_delay(n, 1.0, 20.0, jitter=False) for n in (1, 2, 3, 4, 6)] == [1, 2, 4, 8, 20]


class FakeCall:
    """Raises the given errors in order, then returns 'ok'."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


async def _no_sleep(_):
    return None


def _breaker(threshold=10):
    return CircuitBreaker(failure_threshold=threshold, cooldown_seconds=60)


async def _run(fn, breaker=None, max_retries=3):
    return await call_with_retry(
        fn,
        breaker=breaker or _breaker(),
        max_retries=max_retries,
        base_delay=1,
        max_delay=20,
        sleep=_no_sleep,
        jitter=False,
    )


async def test_temporary_error_then_success():
    fn = FakeCall(openai.APITimeoutError(request=REQUEST), openai.APITimeoutError(request=REQUEST))
    result, attempts = await _run(fn)
    assert (result, attempts, fn.calls) == ("ok", 3, 3)


async def test_gives_up_after_max_retries():
    fn = FakeCall(*[openai.APIConnectionError(request=REQUEST)] * 10)
    with pytest.raises(LLMUnavailableError) as err:
        await _run(fn, max_retries=3)
    assert fn.calls == 4  # 1 try + 3 retries, then stop
    assert err.value.attempts == 4


async def test_permanent_error_is_not_retried():
    fn = FakeCall(_status_error(openai.AuthenticationError, 401))
    with pytest.raises(LLMConfigError) as err:
        await _run(fn)
    assert fn.calls == 1
    assert err.value.code == "invalid_api_key"


async def test_quota_error_is_not_retried():
    fn = FakeCall(_status_error(openai.RateLimitError, 429, {"code": "insufficient_quota"}))
    with pytest.raises(LLMConfigError):
        await _run(fn)
    assert fn.calls == 1


async def test_breaker_opens_and_blocks_calls():
    breaker = _breaker(threshold=2)
    fn = FakeCall(*[openai.APIConnectionError(request=REQUEST)] * 10)
    with pytest.raises(CircuitOpenError):
        await _run(fn, breaker=breaker, max_retries=5)
    assert fn.calls == 2  # stopped as soon as the breaker opened
    assert breaker.state == BreakerState.OPEN


def test_breaker_half_open_after_cooldown_and_closes_on_success():
    clock = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60, clock=lambda: clock[0])
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == BreakerState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
    clock[0] = 61
    assert breaker.state == BreakerState.HALF_OPEN
    breaker.before_call()  # trial call allowed
    breaker.record_success()
    assert breaker.state == BreakerState.CLOSED


def test_breaker_reopens_when_trial_fails():
    clock = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60, clock=lambda: clock[0])
    breaker.record_failure()
    clock[0] = 61
    breaker.record_failure()  # trial failed
    assert breaker.state == BreakerState.OPEN
