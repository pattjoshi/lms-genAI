"""The guardrail log (A9): one `guardrail_events` row per refused message or flagged answer (Phase 7)."""

from app.guardrails.input import Verdict
from app.guardrails.output import BLOCKING
from app.models import GuardrailEvent, User


def input_event(user: User | None, text: str, verdict: Verdict, surface: str) -> GuardrailEvent:
    return GuardrailEvent(
        user_id=user.id if user else None,
        surface=surface,
        stage="input",
        kind=verdict.kind or "off_topic",
        action="blocked",
        method=verdict.method,
        text=text[:500],
        detail={"reason": verdict.reason, "similarity": verdict.similarity, **verdict.detail},
    )


def output_events(user: User | None, text: str, checks: dict, surface: str, blocked: bool = False) -> list:
    """One row per flag. `blocked`: the answer was replaced (non-streamed answers only)."""
    detail = {k: v for k, v in checks.items() if k != "flags"}
    return [
        GuardrailEvent(
            user_id=user.id if user else None,
            surface=surface,
            stage="output",
            kind=flag,
            action="blocked" if blocked and flag in BLOCKING else "flagged",
            method="code",
            text=text[:500],
            detail=detail,
        )
        for flag in checks.get("flags", [])
    ]
