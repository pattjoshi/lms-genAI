"""Langfuse tracing.

Every LangChain call gets a Langfuse callback handler, so each request shows up in
Langfuse as a trace: prompt, response, tokens, cost, latency, user and feature.

Rule: tracing must NEVER break the app. If keys are missing or Langfuse is down,
we log a warning and continue without tracing.
"""

import logging
from contextlib import contextmanager

from app.config import Settings
from app.models import User

log = logging.getLogger(__name__)

_client = None  # langfuse.Langfuse once initialised


def init_tracing(settings: Settings) -> bool:
    global _client
    if not settings.langfuse_enabled:
        log.info("Langfuse keys not set: tracing disabled.")
        return False
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
            environment=settings.app_env,
        )
        log.info("Langfuse tracing enabled (%s).", settings.langfuse_base_url)
        return True
    except Exception:  # noqa: BLE001
        log.warning("Could not start Langfuse; continuing without tracing.", exc_info=True)
        _client = None
        return False


def langfuse_callbacks(settings: Settings) -> list:
    """LangChain callbacks list: [handler] when tracing works, [] otherwise."""
    if _client is None:
        return []
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler(public_key=settings.langfuse_public_key)]
    except Exception:  # noqa: BLE001
        log.warning("Could not create Langfuse handler; this call is not traced.", exc_info=True)
        return []


def trace_metadata(user: User | None, feature: str, session_id: str | None = None) -> dict:
    """LangChain `metadata` keys that Langfuse turns into user / session / tags on the trace."""
    meta: dict = {"langfuse_tags": [feature]}
    if user is not None:
        meta["langfuse_user_id"] = f"{user.role.value}-{user.id}"
        meta["langfuse_tags"].append(user.role.value)
    if session_id:
        meta["langfuse_session_id"] = session_id
    return meta


def shutdown_tracing() -> None:
    if _client is None:
        return
    try:
        _client.flush()
        _client.shutdown()
    except Exception:  # noqa: BLE001
        log.warning("Langfuse flush failed on shutdown.", exc_info=True)


def tracing_enabled() -> bool:
    return _client is not None


# ---------------------------------------------------------------------------
# Spans: group several steps (embed -> retrieve -> generate) into ONE trace.
# ---------------------------------------------------------------------------


class _NoopSpan:
    def update(self, **_kwargs) -> None:
        pass


@contextmanager
def observe(name: str, as_type: str = "span", **fields):
    """A Langfuse observation (span, retriever, embedding...) around a block of code.

    LangChain calls made inside the block are nested under it automatically.
    No-op when tracing is off; tracing errors never reach the caller.
    """
    if _client is None:
        yield _NoopSpan()
        return
    try:
        cm = _client.start_as_current_observation(name=name, as_type=as_type, **fields)
        span = cm.__enter__()
    except Exception:  # noqa: BLE001
        log.debug("Could not start span %s", name, exc_info=True)
        yield _NoopSpan()
        return
    try:
        yield span
    finally:
        try:
            cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            log.debug("Could not end span %s", name, exc_info=True)


@contextmanager
def trace(name: str, user: User | None, feature: str, input=None, session_id: str | None = None):
    """Root of a multi-step trace, with user / tags / session set for every nested step."""
    if _client is None:
        yield _NoopSpan()
        return
    try:
        from langfuse import propagate_attributes

        attrs = propagate_attributes(
            user_id=f"{user.role.value}-{user.id}" if user else None,
            session_id=session_id,
            tags=[feature] + ([user.role.value] if user else []),
            trace_name=name,
        )
        attrs.__enter__()
    except Exception:  # noqa: BLE001
        log.debug("Could not propagate trace attributes", exc_info=True)
        attrs = None
    try:
        with observe(name, as_type="chain", input=input) as span:
            yield span
    finally:
        if attrs is not None:
            try:
                attrs.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                log.debug("Could not close trace attributes", exc_info=True)


# ---------------------------------------------------------------------------
# Phase 7: links from the app to Langfuse, and scores on traces
# ---------------------------------------------------------------------------

_trace_url_prefix: str | None = None


def current_trace_id() -> str | None:
    """The Langfuse trace the code is running inside (None without tracing). Saved with each usage row
    and chat message, so the dashboard can link a slow or expensive call to its trace."""
    if _client is None:
        return None
    try:
        return _client.get_current_trace_id()
    except Exception:  # noqa: BLE001
        return None


def trace_url(trace_id: str | None) -> str | None:
    """Link to a trace in the Langfuse UI. The project id is looked up once (one API call), then cached."""
    global _trace_url_prefix
    if _client is None or not trace_id:
        return None
    if _trace_url_prefix is None:
        try:
            url = _client.get_trace_url(trace_id="TRACE")
        except Exception:  # noqa: BLE001
            log.debug("Could not build a Langfuse trace URL", exc_info=True)
            return None
        if not url:
            return None
        _trace_url_prefix = url.removesuffix("TRACE")
    return _trace_url_prefix + trace_id


def score(trace_id: str | None, name: str, value: float, comment: str | None = None) -> None:
    """Attach a score (e.g. faithfulness from the eval) to a trace, so Langfuse can chart it."""
    if _client is None or not trace_id:
        return
    try:
        _client.create_score(name=name, value=value, trace_id=trace_id, comment=comment)
    except Exception:  # noqa: BLE001
        log.debug("Could not send score %s", name, exc_info=True)
