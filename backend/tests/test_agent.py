"""Phase 4a: routing rules, the embedding router's decision, memory and support replies. No LLM, no DB."""

from datetime import UTC, datetime, timedelta

import pytest

from app.agent.graph import confidence
from app.agent.intents import Intent, clean_topic, extract_topic, match_rules
from app.agent.memory import TopicScore, merge_weak
from app.agent.router import nearest_intent
from app.agent.support import is_login_problem, login_reply, payment_reply
from app.models import LearnerTopic, LoginEvent, Payment, PaymentMethod, PaymentStatus


@pytest.mark.parametrize(
    ("text", "intent", "topic"),
    [
        ("I don't understand backpropagation", Intent.learning_path, "backpropagation"),
        ("i dont get the chain rule at all", Intent.learning_path, "chain rule"),
        ("I'm confused about gradient descent.", Intent.learning_path, "gradient descent"),
        ("What should I learn before neural networks?", Intent.learning_path, "neural networks"),
        ("Quiz me on SQL joins", Intent.practice, "SQL joins"),
        ("give me some practice questions", Intent.practice, None),
        ("quiz me on my weak topics", Intent.practice, None),
        ("What are my weak topics?", Intent.progress, None),
        ("how am I doing", Intent.progress, None),
        ("I can't log in to my account", Intent.support, None),
        ("I forgot my password", Intent.support, None),
        ("My payment failed but money was deducted", Intent.support, None),
        ("I want a refund", Intent.support, None),
    ],
)
def test_rules(text, intent, topic):
    hit = match_rules(text)
    assert hit is not None and hit.intent == intent
    assert extract_topic(text) == topic


@pytest.mark.parametrize(
    "text",
    [
        "How does backpropagation compute gradients?",
        "What is a transaction in SQL and why does it need a rollback?",  # course word, not a payment
        "Explain the payments table in the sample database",
        "What is the difference between a list and a tuple?",
        "Can you give an example?",
    ],
)
def test_course_questions_are_not_caught_by_rules(text):
    assert match_rules(text) is None


def test_topic_cleanup():
    assert clean_topic("the chain rule properly?") == "chain rule"
    assert clean_topic("it") is None
    assert clean_topic("why my code keeps failing when I run the second cell") is None  # too long: not a concept


def test_nearest_intent_needs_similarity_and_margin():
    examples = [(Intent.doubt, [1.0, 0.0]), (Intent.practice, [0.0, 1.0])]
    assert nearest_intent([1.0, 0.1], examples, 0.45, 0.04)[0] == Intent.doubt
    assert nearest_intent([0.7, 0.7], examples, 0.45, 0.04)[0] is None  # a tie: ambiguous
    assert nearest_intent([0.1, -1.0], examples, 0.45, 0.04)[0] is None  # nothing similar enough


def lt(topic, kind, count=1, days_ago=0):
    return LearnerTopic(
        topic=topic, key=topic.lower(), kind=kind, count=count, last_at=datetime.now(UTC) - timedelta(days=days_ago)
    )


def test_weak_topics_merge_quiz_scores_and_what_the_student_said():
    scores = {"joins": TopicScore("Joins", "DB101", 40, 3), "loops": TopicScore("Loops", "PY101", 90, 2)}
    weak = merge_weak(scores, [lt("Chain Rule", "asked_path", 2), lt("Joins", "practice_wrong")], 65)
    assert [w.name for w in weak] == ["Joins", "Chain Rule"]
    assert "quiz average 40%" in weak[0].why and "1 practice answer wrong" in weak[0].why
    assert "(2×)" in weak[1].why


def test_practising_a_topic_right_clears_it():
    struggles = [lt("Recursion", "practice_wrong", 2), lt("Recursion", "practice_right", 2)]
    assert merge_weak({}, struggles, 65) == []
    struggles = [lt("Recursion", "asked_path"), lt("Recursion", "practice_right", 1)]
    assert merge_weak({}, struggles, 65) == []


def test_confidence():
    assert confidence({"by": "rerank", "best": 0.9, "threshold": 0.3}) == "high"
    assert confidence({"by": "rerank", "best": 0.45, "threshold": 0.3}) == "medium"
    assert confidence({"by": "rerank", "best": 0.32, "threshold": 0.3}) == "low"
    assert confidence({"by": "cosine", "best": None, "threshold": 0.3}) == "low"


def test_login_reply_uses_own_records():
    now = datetime.now(UTC)

    def failed(reason, hours):
        at = now - timedelta(hours=hours)
        return LoginEvent(success=False, failure_reason=reason, device="android", occurred_at=at)

    events = [failed("account_locked", 20), failed("wrong_password", 21)]
    text, facts = login_reply(events, now)
    assert "2 failed logins" in text and "account locked" in text and "Forgot password" in text
    assert facts["reasons"] == ["account_locked", "wrong_password"]
    assert "look fine" not in text
    assert "looks fine" in login_reply([], now)[0]
    assert is_login_problem("my otp expired") and not is_login_problem("my payment failed")


def test_payment_reply_explains_failed_payments():
    now = datetime.now(UTC)
    p = Payment(
        amount_inr=4999,
        status=PaymentStatus.failed,
        method=PaymentMethod.upi,
        failure_reason="bank declined",
        created_at=now - timedelta(days=3),
    )
    text, facts = payment_reply([(p, "DL301")], now)
    assert "DL301: ₹4999 by upi, failed (bank declined), 3 days ago" in text
    assert "reversed by the bank" in text and facts["failed_or_pending"] == 1
