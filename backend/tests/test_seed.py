"""The planted stories are the known correct answers for later evals. Keep them true."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean

import pytest

from app.models import EnrollmentStatus, PaymentStatus, Role
from app.seed.build import IST, build_seed

NOW = datetime(2026, 10, 3, 6, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def data():
    return build_seed(now=NOW)


@pytest.fixture(scope="module")
def scores_by_topic(data):
    topic_of_quiz = {q.id: q.topic_id for q in data.quizzes}
    topic_name = {t.id: t.name for t in data.topics}
    out = defaultdict(list)
    for a in data.attempts:
        out[(a.student_id, topic_name[topic_of_quiz[a.quiz_id]])].append(a.score_pct)
    return out


def _user(data, email):
    return next(u for u in data.users if u.email == email)


def test_deterministic():
    a, b = build_seed(now=NOW), build_seed(now=NOW)
    assert [u.email for u in a.users] == [u.email for u in b.users]
    assert [x.score_pct for x in a.attempts] == [x.score_pct for x in b.attempts]


def test_counts(data):
    roles = defaultdict(int)
    for u in data.users:
        roles[u.role] += 1
    assert roles == {Role.admin: 1, Role.support: 2, Role.teacher: 6, Role.student: 150}
    assert len(data.courses) == 6
    assert len({u.email for u in data.users}) == len(data.users)


def test_nothing_in_the_future(data):
    assert max(a.attempted_at for a in data.attempts) <= NOW
    assert max(p.created_at for p in data.payments) <= NOW
    assert max(e.occurred_at for e in data.logins) <= NOW


def test_riya_weak_in_backprop_and_chain_rule(data, scores_by_topic):
    riya = _user(data, "riya.sharma@student.lmsdemo.in")
    assert mean(scores_by_topic[(riya.id, "Backpropagation")]) < 45
    assert mean(scores_by_topic[(riya.id, "Chain Rule")]) < 45
    assert mean(scores_by_topic[(riya.id, "Perceptron")]) > 55  # weak only where planted


def test_sql_joins_is_hardest_topic(data, scores_by_topic):
    per_topic = defaultdict(list)
    for (_, topic), scores in scores_by_topic.items():
        per_topic[topic].extend(scores)
    averages = {t: mean(s) for t, s in per_topic.items()}
    assert min(averages, key=averages.get) == "SQL Joins"
    joins = per_topic["SQL Joins"]
    assert sum(s < 50 for s in joins) / len(joins) > 0.7  # most students fail


def test_ananya_is_top_performer(data):
    per_student = defaultdict(list)
    for a in data.attempts:
        per_student[a.student_id].append(a.score_pct)
    best = max(per_student, key=lambda s: mean(per_student[s]))
    assert best == _user(data, "ananya.iyer@student.lmsdemo.in").id


def test_exactly_five_students_with_failed_payments_last_30_days(data):
    since = NOW - timedelta(days=30)
    students = {p.student_id for p in data.payments if p.status == PaymentStatus.failed and p.created_at >= since}
    assert len(students) == 5
    assert _user(data, "arjun.mehta@student.lmsdemo.in").id in students


def test_nlp_has_highest_drop_rate(data):
    code = {c.id: c.code for c in data.courses}
    totals, dropped = defaultdict(int), defaultdict(int)
    for e in data.enrollments:
        totals[code[e.course_id]] += 1
        dropped[code[e.course_id]] += e.status == EnrollmentStatus.dropped
    rates = {c: dropped[c] / totals[c] for c in totals}
    assert max(rates, key=rates.get) == "NLP302"


def test_karan_locked_out_yesterday(data):
    yesterday = NOW.astimezone(IST).date() - timedelta(days=1)
    failed = defaultdict(int)
    for e in data.logins:
        if not e.success and e.occurred_at.astimezone(IST).date() == yesterday:
            failed[e.user_id] += 1
    karan = _user(data, "karan.verma@student.lmsdemo.in")
    assert failed[karan.id] == 6
    assert all(n < 3 for uid, n in failed.items() if uid != karan.id)
    last_success = max(e.occurred_at for e in data.logins if e.user_id == karan.id and e.success)
    assert last_success.astimezone(IST).date() < yesterday
