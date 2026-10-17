"""Input guardrail: should the assistant answer this message at all? (Phase 7)

    1. rules        regexes for known prompt-injection phrasings       free, ~0 ms, precise but narrow
    2. embeddings   similar to a course topic or a known kind of request?  one embedding call, shared with
                                                                        the router, so it costs nothing extra
    3. LLM          {verdict: ok | off_topic | injection, reason}        one small call, only when 1-2 are unsure

Same shape as the router (app/agent/router.py), cheapest first. The embedding step can only ALLOW: a low
similarity doesn't prove a message is off topic ("what is gradient clipping?" is a fair question the material
may not cover), so it is handed to the LLM instead of being refused.

What this layer is and isn't: it is LAYER 1 of the permission design (PLAN.md), a soft layer for UX and cost:
off-topic questions get a polite reply instead of a search, a "no answer" and a support ticket; obvious
injections are refused and logged. It is not a security boundary. A clever enough message gets past any
classifier, which is why a student's agent never has staff tools (layer 2) and every query is scoped by the
database (layer 3). The guardrail fails OPEN: if the classifier errors, the message is answered.
"""

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intents import EXAMPLES
from app.config import get_settings
from app.ingest.tagger import cosine
from app.llm.service import chat_structured, embed_texts
from app.llm.tracing import observe
from app.models import Course, Module, Topic, User
from app.prompts.guardrail import GUARD_SYSTEM, GUARD_USER, INJECTION_REPLY, OFF_TOPIC_REPLY

log = logging.getLogger(__name__)


@dataclass
class Verdict:
    allowed: bool
    kind: Literal["injection", "off_topic"] | None  # why it was blocked
    method: Literal["rules", "embedding", "llm", "off", "error"]
    reason: str = ""
    similarity: float | None = None  # best similarity to a course topic / request example
    vector: list[float] | None = None  # the message's embedding, handed on to the router
    cost_usd: float = 0.0
    detail: dict = field(default_factory=dict)

    @property
    def reply(self) -> str | None:
        """The fixed text shown instead of an answer."""
        if self.allowed:
            return None
        return INJECTION_REPLY if self.kind == "injection" else OFF_TOPIC_REPLY

    def out(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in ("vector", "cost_usd")}


# ---------------------------------------------------------------------------
# 1. Rules: phrasings that are only ever used to attack an assistant
# ---------------------------------------------------------------------------

_I = re.IGNORECASE
# Written for precision, like the router's rules: a rule that fires blocks the message with no second opinion,
# so each one needs words a real question wouldn't use. "I always forget the rules of 3NF" and "what is a
# system prompt?" (an NLP302 question) must pass; tests/test_guardrails.py keeps a list of such questions.
_PRIOR = r"(previous|prior|above|earlier|preceding|initial|original|all|your|these|those)"
INJECTION_RULES: list[tuple[str, re.Pattern]] = [
    (
        "ignore_instructions",
        re.compile(
            rf"\b(ignore|disregard|forget|override|bypass)\b(\s+{_PRIOR}){{1,3}}\s+"
            r"(instructions?|rules?|prompts?|guidelines|directions|restrictions|guardrails|filters)\b",
            _I,
        ),
    ),
    (
        "reveal_prompt",
        re.compile(
            r"\b(reveal|print|show|repeat|output|display|tell me|give me|leak|dump)\b.{0,40}"
            r"(\byour\s+(system\s+|hidden\s+|initial\s+|secret\s+)?(prompt|instructions)\b"
            r"|\b(hidden|secret)\s+(prompt|instructions)\b)",
            _I,
        ),
    ),
    ("reveal_prompt", re.compile(r"\b(repeat|print|output)\b.{0,30}\b(everything|all|text)\b.{0,15}\babove\b", _I)),
    (
        "role_play",
        re.compile(
            r"\b(you are now|from now on,? you are|act as|pretend (to be|you are)|roleplay as)\b.{0,40}"
            r"\b(unrestricted|unfiltered|jailbroken|dan|admin|administrator|developer mode|no (rules|limits))\b",
            _I,
        ),
    ),
    ("jailbreak", re.compile(r"\b(jailbreak|developer mode|do anything now|dan mode)\b", _I)),
    ("role_claim", re.compile(r"\b(i am|i'm|im)\s+(the|your)\s+(admin|administrator|superuser)\b", _I)),
    (
        "fake_system_tag",
        re.compile(r"(<\s*/?\s*system\s*>|\[\s*system\s*\]|^\s*#+\s*system\b|^\s*system\s*:)", _I | re.M),
    ),
]


def match_injection(text: str) -> str | None:
    """Name of the first injection rule that matches, or None."""
    for name, pattern in INJECTION_RULES:
        if pattern.search(text):
            return name
    return None


# ---------------------------------------------------------------------------
# 2. Embeddings: anchors = the LMS's topic names + the router's example requests (cached per process)
# ---------------------------------------------------------------------------

_anchors: dict[str, list[list[float]]] = {}  # embedding model -> anchor vectors
_courses: list[str] = []  # course titles, for the LLM prompt


async def _load_courses(session: AsyncSession) -> list[str]:
    global _courses
    if not _courses:
        rows = (await session.execute(select(Course.code, Course.title).order_by(Course.code))).all()
        _courses = [f"{title} ({code})" for code, title in rows]
    return _courses


async def _anchor_vectors(session: AsyncSession) -> list[list[float]]:
    model = get_settings().openai_embedding_model
    if model not in _anchors:
        rows = (
            await session.execute(
                select(Topic.name, Course.title)
                .join(Module, Module.id == Topic.module_id)
                .join(Course, Course.id == Module.course_id)
            )
        ).all()
        texts = [f"{topic} ({course})" for topic, course in rows]
        texts += [example for examples in EXAMPLES.values() for example in examples]
        embedded = await embed_texts(session, texts, feature="guard_anchors", user=None)
        _anchors[model] = embedded.vectors
    return _anchors[model]


def best_similarity(vector: list[float], anchors: list[list[float]]) -> float:
    return max((cosine(vector, a) for a in anchors), default=0.0)


# ---------------------------------------------------------------------------
# 3. LLM classifier
# ---------------------------------------------------------------------------


class GuardChoice(BaseModel):
    verdict: Literal["ok", "off_topic", "injection"]
    reason: str = Field(description="Why, in at most 12 words.")


async def _llm_check(session: AsyncSession, user: User, text: str) -> tuple[GuardChoice, float]:
    courses = ", ".join(await _load_courses(session)) or "programming and data science courses"
    choice, result = await chat_structured(
        session,
        messages=[SystemMessage(GUARD_SYSTEM.format(courses=courses)), HumanMessage(GUARD_USER.format(text=text))],
        schema=GuardChoice,
        feature="guard_input",
        user=user,
        max_tokens=get_settings().guard_max_output_tokens,
    )
    return choice, result.cost_usd


# ---------------------------------------------------------------------------
# All three
# ---------------------------------------------------------------------------


async def check_input(session: AsyncSession, user: User, text: str) -> Verdict:
    s = get_settings()
    if not s.guardrails:
        return Verdict(True, None, "off")
    with observe("guardrail_input", as_type="guardrail", input={"text": text}) as span:
        verdict = await _check(session, user, text)
        span.update(output=verdict.out())
    return verdict


async def _check(session: AsyncSession, user: User, text: str) -> Verdict:
    s = get_settings()
    # 1. Rules
    if rule := match_injection(text):
        return Verdict(False, "injection", "rules", f"matched rule {rule}", detail={"rule": rule})

    # 2. Embeddings (the vector is reused by the router)
    cost, vector, similarity = 0.0, None, None
    try:
        embedded = await embed_texts(session, [text], feature="guard_embed", user=user)
        cost, vector = embedded.cost_usd, embedded.vectors[0]
        similarity = round(best_similarity(vector, await _anchor_vectors(session)), 3)
        if similarity >= s.guard_on_topic_similarity:
            return Verdict(True, None, "embedding", "close to a course topic", similarity, vector, cost)
    except Exception as exc:  # noqa: BLE001 - the LLM step can still decide
        log.warning("Guardrail embedding step failed: %s", exc)

    # 3. LLM
    try:
        choice, llm_cost = await _llm_check(session, user, text)
    except Exception as exc:  # noqa: BLE001 - fail open: layers 2 and 3 still hold
        log.warning("Guardrail classifier failed, answering anyway: %s", exc)
        return Verdict(True, None, "error", type(exc).__name__, similarity, vector, cost)
    cost += llm_cost
    if choice.verdict == "ok":
        return Verdict(True, None, "llm", choice.reason, similarity, vector, cost)
    return Verdict(False, choice.verdict, "llm", choice.reason, similarity, vector, cost)
