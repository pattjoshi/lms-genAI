"""Turn any exception from an LLM call into one of two kinds:

- TEMPORARY: may work if we try again (timeout, network, OpenAI overloaded, rate limit).
- PERMANENT: will fail the same way every time (bad key, no credit, unknown model,
  bad request). Retrying these only wastes time and money, so we stop at once.

Unknown exceptions are treated as PERMANENT: we never retry a bug we don't understand.
"""

import asyncio
from dataclasses import dataclass
from enum import StrEnum

import openai


class ErrorKind(StrEnum):
    TEMPORARY = "temporary"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class Classified:
    kind: ErrorKind
    code: str
    user_message: str
    trips_breaker: bool  # should this failure count towards opening the circuit breaker?


def classify(exc: BaseException) -> Classified:
    # Order matters: APITimeoutError is a subclass of APIConnectionError.
    if isinstance(exc, (openai.APITimeoutError, asyncio.TimeoutError, TimeoutError)):
        return Classified(ErrorKind.TEMPORARY, "timeout", "The AI took too long to respond.", True)
    if isinstance(exc, openai.APIConnectionError):
        return Classified(ErrorKind.TEMPORARY, "connection_error", "Could not reach the AI service.", True)
    if isinstance(exc, openai.RateLimitError):
        # OpenAI uses HTTP 429 both for "slow down" and for "you have no credit left".
        # Only the first one is worth retrying.
        if _is_quota_error(exc):
            return Classified(
                ErrorKind.PERMANENT,
                "quota_exceeded",
                "The OpenAI account is out of credit or hit its spending limit.",
                True,
            )
        return Classified(ErrorKind.TEMPORARY, "rate_limited", "The AI is busy right now.", True)
    if isinstance(exc, openai.AuthenticationError):
        return Classified(ErrorKind.PERMANENT, "invalid_api_key", "The OpenAI API key is invalid.", True)
    if isinstance(exc, openai.PermissionDeniedError):
        return Classified(ErrorKind.PERMANENT, "permission_denied", "The OpenAI key has no access to this model.", True)
    if isinstance(exc, openai.NotFoundError):
        return Classified(
            ErrorKind.PERMANENT,
            "model_not_found",
            "The configured OpenAI model does not exist. Check OPENAI_CHAT_MODEL in .env.",
            False,
        )
    if isinstance(exc, (openai.BadRequestError, openai.UnprocessableEntityError)):
        # e.g. prompt too long. It's this request's fault, not the service's: don't trip the breaker.
        return Classified(ErrorKind.PERMANENT, "bad_request", "The AI rejected this request.", False)
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500 or exc.status_code == 409:
            return Classified(ErrorKind.TEMPORARY, "server_error", "The AI service had an internal error.", True)
        return Classified(ErrorKind.PERMANENT, f"http_{exc.status_code}", "The AI rejected this request.", False)
    return Classified(ErrorKind.PERMANENT, "unexpected_error", "Something went wrong while calling the AI.", False)


def _is_quota_error(exc: openai.RateLimitError) -> bool:
    text = f"{getattr(exc, 'code', '')} {getattr(exc, 'type', '')} {exc}".lower()
    return "insufficient_quota" in text or "quota" in text or "billing" in text


# ---------------------------------------------------------------------------
# Exceptions our own code raises. main.py turns them into clean JSON responses.
# ---------------------------------------------------------------------------


class LLMError(Exception):
    http_status = 503

    def __init__(self, user_message: str, *, code: str, detail: str | None = None, attempts: int = 1):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code
        self.detail = detail  # technical detail: logged, and shown only when APP_ENV=dev
        self.attempts = attempts


class LLMUnavailableError(LLMError):
    """Temporary error that was still failing after all retries."""

    http_status = 503


class LLMConfigError(LLMError):
    """Permanent error: needs a human to fix something (key, credit, model name, request)."""

    http_status = 500


class CircuitOpenError(LLMError):
    """Too many failures recently; calls are paused for a cooldown."""

    http_status = 503


class DailyBudgetExceededError(LLMError):
    http_status = 429
