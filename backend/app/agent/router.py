"""Intent routing: which part of the LMS should handle this message? (Phase 4)

    1. rules        regexes in intents.py             free, ~0 ms, precise but narrow
    2. embeddings   nearest example per intent         one embedding call (~$0.000001), ~100 ms
    3. LLM          structured output {intent, topic}  one small LLM call, only when 1 and 2 are unsure

Each step only answers when it is confident; otherwise the message falls through to the next one. Most
messages are plain course questions, which the embedding step settles, so the LLM runs rarely. The
decision (method, confidence, runner-up) is saved with the message and shown in the chat, so a wrong
route can be traced to the step that made it.
"""

import logging
from dataclasses import asdict, dataclass, field
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intents import EXAMPLES, NEEDS_TOPIC, Intent, clean_topic, extract_topic, match_rules
from app.config import get_settings
from app.ingest.tagger import cosine
from app.llm.service import chat_structured, embed_texts
from app.models import User
from app.prompts.route import ROUTE_SYSTEM, ROUTE_USER

log = logging.getLogger(__name__)


@dataclass
class Route:
    intent: Intent
    method: Literal["rules", "embedding", "llm", "default"]
    confidence: float  # rules 1.0; embedding: similarity of the nearest example; llm: 0.8 (it can't tell us)
    topic: str | None = None
    detail: dict = field(default_factory=dict)  # rule that fired / scores per intent
    cost_usd: float = 0.0

    def out(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "cost_usd"}


# ---------------------------------------------------------------------------
# 2. Embeddings: nearest example. The examples are embedded once per process and cached.
# ---------------------------------------------------------------------------

_example_vectors: dict[str, list[tuple[Intent, list[float]]]] = {}  # embedding model -> vectors


async def _examples(session: AsyncSession) -> list[tuple[Intent, list[float]]]:
    model = get_settings().openai_embedding_model
    if model not in _example_vectors:
        pairs = [(intent, text) for intent, texts in EXAMPLES.items() for text in texts]
        embedded = await embed_texts(session, [t for _, t in pairs], feature="route_examples", user=None)
        _example_vectors[model] = [(intent, v) for (intent, _), v in zip(pairs, embedded.vectors, strict=True)]
    return _example_vectors[model]


def nearest_intent(
    vector: list[float], examples: list[tuple[Intent, list[float]]], min_similarity: float, min_margin: float
) -> tuple[Intent | None, dict[str, float]]:
    """Best similarity per intent (max over its examples). Confident only if the best intent is similar
    enough AND clearly ahead of the runner-up: two close scores mean the message is ambiguous."""
    best: dict[str, float] = {}
    for intent, v in examples:
        best[intent] = max(best.get(intent, -1.0), cosine(vector, v))
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    scores = {k: round(v, 3) for k, v in ranked}
    if not ranked:
        return None, scores
    (top, s1), s2 = ranked[0], (ranked[1][1] if len(ranked) > 1 else -1.0)
    if s1 >= min_similarity and s1 - s2 >= min_margin:
        return Intent(top), scores
    return None, scores


# ---------------------------------------------------------------------------
# 3. LLM: a small structured-output classifier
# ---------------------------------------------------------------------------


class RouteChoice(BaseModel):
    intent: Literal["doubt", "learning_path", "practice", "progress", "support", "assistant"]
    topic: str = Field(description="The concept or topic the student names, 1-6 words. Empty string if none.")


async def _llm_route(session: AsyncSession, user: User, text: str) -> tuple[RouteChoice, float]:
    examples = "\n".join(f"- {i.value}: " + " | ".join(ex[:3]) for i, ex in EXAMPLES.items())
    choice, result = await chat_structured(
        session,
        messages=[SystemMessage(ROUTE_SYSTEM.format(examples=examples)), HumanMessage(ROUTE_USER.format(text=text))],
        schema=RouteChoice,
        feature="route_intent",
        user=user,
        max_tokens=get_settings().route_max_output_tokens,
    )
    return choice, result.cost_usd


# ---------------------------------------------------------------------------
# All three
# ---------------------------------------------------------------------------


async def route(session: AsyncSession, user: User, text: str) -> Route:
    s = get_settings()
    topic = extract_topic(text)

    # 1. Rules
    if hit := match_rules(text):
        if hit.intent not in NEEDS_TOPIC or topic:
            return Route(hit.intent, "rules", 1.0, topic, {"rule": hit.rule})
        # e.g. "I don't understand" with no topic we can pick out: let the LLM read it

    # 2. Embeddings
    cost = 0.0
    if not (hit and hit.intent in NEEDS_TOPIC):
        embedded = await embed_texts(session, [text], feature="route_embed", user=user)
        cost += embedded.cost_usd
        intent, scores = nearest_intent(
            embedded.vectors[0], await _examples(session), s.route_min_similarity, s.route_min_margin
        )
        if intent is not None and (intent not in NEEDS_TOPIC or topic):
            return Route(intent, "embedding", scores[intent], topic, {"scores": scores}, cost)
        detail = {"scores": scores}
    else:
        detail = {"rule": hit.rule, "note": "rule fired but no topic found"}

    # 3. LLM
    try:
        choice, llm_cost = await _llm_route(session, user, text)
    except Exception as exc:  # noqa: BLE001 - routing must never block a question: answer it as a doubt
        log.warning("LLM router failed, falling back to doubt: %s", exc)
        return Route(Intent.doubt, "default", 0.0, topic, {**detail, "error": type(exc).__name__}, cost)
    intent = Intent(choice.intent)
    topic = clean_topic(choice.topic) if choice.topic else topic
    if intent in NEEDS_TOPIC and not topic:
        intent = Intent.doubt  # a path needs a concept; without one, answering is the useful thing
    return Route(intent, "llm", 0.8, topic, detail, cost + llm_cost)
