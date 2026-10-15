"""The intents the chat understands, and the cheap ways to recognise them (Phase 4).

    doubt          a question about the course material          -> RAG answer with citations (Phase 1-2)
    learning_path  "I don't understand X", "what before X?"      -> study order from the concept graph (Phase 3)
    practice       "quiz me on X", "practice my weak topics"      -> AI practice questions, graded with explanation
    progress       "what are my weak topics?", "how am I doing?"  -> what the assistant remembers about you
    support        login, password, payment, refund problems     -> your own login / payment records + next steps

Routing is done cheapest first (router.py): these RULES, then EMBEDDINGS against the EXAMPLES below,
and only if both are unsure, an LLM. Rules are written for precision, not recall: a rule that fires must
be right, because nothing checks it afterwards. Anything they miss falls through to the next step.
"""

import re
from dataclasses import dataclass
from enum import StrEnum


class Intent(StrEnum):
    doubt = "doubt"
    learning_path = "learning_path"
    practice = "practice"
    progress = "progress"
    support = "support"


# What each intent sounds like. Used by the embedding router (nearest examples) and shown to the LLM
# router. Add a line here when a real question is routed wrongly: that's the cheapest fix.
EXAMPLES: dict[Intent, list[str]] = {
    Intent.doubt: [
        "How does backpropagation compute gradients?",
        "What is the difference between a list and a tuple?",
        "Explain the chain rule with an example",
        "Why does my model overfit?",
        "What does a primary key do?",
        "Can you give an example of a left join?",
        "When should I use a dictionary instead of a list?",
        "What is the learning rate in gradient descent?",
    ],
    Intent.learning_path: [
        "I don't understand backpropagation",
        "I'm lost with recursion",
        "What should I learn before neural networks?",
        "Backpropagation makes no sense to me",
        "What do I need to know first to understand joins?",
        "I'm struggling with gradient descent, where do I start?",
        "Show me the prerequisites for convolutional networks",
    ],
    Intent.practice: [
        "Quiz me on gradient descent",
        "Give me some practice questions",
        "Test me on SQL joins",
        "I want to practise my weak topics",
        "Can I get a few questions to check my understanding of recursion?",
        "Practice questions about activation functions please",
    ],
    Intent.progress: [
        "What are my weak topics?",
        "How am I doing in my courses?",
        "Which topics should I revise?",
        "What am I bad at?",
        "Show me my quiz scores",
        "What do you remember about me?",
    ],
    Intent.support: [
        "I can't log in to my account",
        "My payment failed but money was deducted",
        "I forgot my password",
        "My OTP expired and I'm locked out",
        "I want a refund for my course",
        "I was charged twice for the course",
    ],
}

# Intents that need a topic (X). Practice works without one: it uses the weak topics instead.
NEEDS_TOPIC = {Intent.learning_path}

_I = re.IGNORECASE
_RULES: list[tuple[Intent, re.Pattern]] = [
    # support: personal account/payment trouble. Course words like "payments table" must NOT match,
    # so each pattern needs a first-person or problem word next to the account word.
    (
        Intent.support,
        re.compile(
            r"\b(can'?t|cannot|unable to|not able to|couldn'?t|won'?t let me)\s+"
            r"(log ?in|sign ?in|login|access my account)\b",
            _I,
        ),
    ),
    (Intent.support, re.compile(r"\b(forgot|reset|change)\s+(my\s+)?password\b", _I)),
    (Intent.support, re.compile(r"\b(otp|account)\b.{0,30}\b(expired|locked|blocked|not (working|received))\b", _I)),
    (Intent.support, re.compile(r"\blocked out\b", _I)),
    # ("transaction" alone is a SQL topic, so it only counts next to a payment word)
    (Intent.support, re.compile(r"\bmy\s+(payment|refund|purchase|subscription)\b", _I)),
    (Intent.support, re.compile(r"\b(i was|i got|i'?ve been|money|amount)\b.{0,30}\b(charged|deducted|debited)\b", _I)),
    (Intent.support, re.compile(r"\b(want|need|get|request)\s+(a|my)\s+refund\b", _I)),
    (Intent.support, re.compile(r"\bpayment\b.{0,30}\b(failed|pending|declined|stuck|didn'?t go through)\b", _I)),
    # progress
    # "what are my weak topics" is progress; "quiz me on my weak topics" is practice (matched below)
    (Intent.progress, re.compile(r"^(?!.*\b(quiz|practi[cs]e|test me)).*\bweak\s+(topics?|areas?|spots?)\b", _I)),
    (Intent.progress, re.compile(r"\bwhat am i (bad|weak|struggling) (at|with)\b", _I)),
    (Intent.progress, re.compile(r"\bhow am i doing\b", _I)),
    (Intent.progress, re.compile(r"\b(show|what are) my (quiz )?(scores|progress|results)\b", _I)),
    (Intent.progress, re.compile(r"\bwhat do you (remember|know) about me\b", _I)),
    # practice
    (Intent.practice, re.compile(r"\b(quiz|test) me\b", _I)),
    (Intent.practice, re.compile(r"\bpracti[cs]e (questions?|quiz|problems?|my|on|for|about)\b", _I)),
    (Intent.practice, re.compile(r"\b(give|show) me (some |a few |\d+ )?(practice |quiz |mcq )?questions\b", _I)),
    # learning path: "I don't understand X" is the S9 phrase
    (
        Intent.learning_path,
        re.compile(r"\bi\s*(do\s*n[o']?t|don'?t|dont|can'?t|cannot|still don'?t)\s+(understand|get|follow)\b", _I),
    ),
    (Intent.learning_path, re.compile(r"\b(i'?m|i am) (lost|confused|stuck|struggling) (with|about|on|in)\b", _I)),
    (Intent.learning_path, re.compile(r"\bmakes? no sense\b", _I)),
    (Intent.learning_path, re.compile(r"\b(learn|know|study) (first |before )", _I)),
    (Intent.learning_path, re.compile(r"\b(prerequisites?|learning path|study path|study order)\b", _I)),
]

# "X" in the phrases above. Tried in order; the first that captures something wins.
_TOPIC_PATTERNS = [
    re.compile(r"\b(?:understand|get|follow)\s+(?:what\s+|how\s+)?(?:the\s+|a\s+|an\s+)?(?P<t>.+)", _I),
    re.compile(r"\b(?:lost|confused|stuck|struggling)\s+(?:with|about|on|in)\s+(?P<t>.+)", _I),
    re.compile(r"\b(?:quiz|test) me (?:on|about|in)\s+(?P<t>.+)", _I),
    re.compile(r"\bpracti[cs]e(?: questions?| quiz| problems?)? (?:on|for|about|in)\s+(?P<t>.+)", _I),
    re.compile(r"\bquestions? (?:on|about|for)\s+(?P<t>.+)", _I),
    re.compile(r"\b(?:prerequisites?|learning path|study path|study order)\s+(?:of|for|to)\s+(?P<t>.+)", _I),
    re.compile(r"\b(?:before|first to understand|to understand)\s+(?P<t>.+)", _I),
    re.compile(r"^(?P<t>.+?)\s+makes? no sense", _I),
]
_TRAILING = re.compile(
    r"\s*(?:\bat all\b|\bproperly\b|\bvery well\b|\bplease\b|\bpls\b|\byet\b|\bfully\b|\bin class\b|\bagain\b)\s*$", _I
)
_FILLER = re.compile(r"^(?:the|a|an|about|on|this|these|that|those|my|topic of|concept of)\s+", _I)
_GENERIC = {"it", "this", "that", "anything", "everything", "my weak topics", "weak topics", "them", "something"}
MAX_TOPIC_WORDS = 6


@dataclass
class RuleHit:
    intent: Intent
    rule: str  # the pattern that fired, for the "how it was routed" panel


def match_rules(text: str) -> RuleHit | None:
    for intent, pattern in _RULES:
        if pattern.search(text):
            return RuleHit(intent, pattern.pattern)
    return None


def clean_topic(raw: str) -> str | None:
    t = raw.strip().strip("?.!,;:\"'").strip()
    t = re.split(r"\s*(?:[?.!;]|\b(?:because|since|but|and how|can you|could you)\b)", t, maxsplit=1)[0]
    for _ in range(3):
        t = _TRAILING.sub("", _FILLER.sub("", t)).strip()
    if not t or t.lower() in _GENERIC or len(t.split()) > MAX_TOPIC_WORDS:
        # Too long to be a concept name ("why my code fails when I run it twice"): not a topic.
        return None
    return t


def extract_topic(text: str) -> str | None:
    for pattern in _TOPIC_PATTERNS:
        m = pattern.search(text)
        if m and (t := clean_topic(m.group("t"))):
            return t
    return None
