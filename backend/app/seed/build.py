"""Builds all dummy LMS data in memory (no database needed).

Fixed random seed => same data every run, so eval answers stay valid.
Dates are relative to `now`, so "last 30 days" questions always have answers.

The planted stories (see data/seed_stories.md) are written explicitly below and
checked by tests/test_seed.py — later phases use them as known correct answers.
"""

import itertools
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from faker import Faker

from app.models import (
    Course,
    Difficulty,
    Enrollment,
    EnrollmentStatus,
    LoginEvent,
    Module,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Quiz,
    QuizAttempt,
    Role,
    Topic,
    User,
)
from app.seed.catalog import ADMIN, COURSES, STORY_STUDENTS, SUPPORT

IST = ZoneInfo("Asia/Kolkata")

CITIES = [
    "Mumbai",
    "Delhi",
    "Bengaluru",
    "Hyderabad",
    "Chennai",
    "Kolkata",
    "Pune",
    "Ahmedabad",
    "Jaipur",
    "Lucknow",
    "Bhubaneswar",
    "Indore",
    "Kochi",
    "Chandigarh",
    "Nagpur",
    "Patna",
    "Coimbatore",
    "Guwahati",
]
COURSE_POPULARITY = {"PY101": 0.70, "ML201": 0.45, "DL301": 0.30, "NLP302": 0.30, "DB201": 0.40, "DSA201": 0.40}
DROP_RATE = {"NLP302": 0.35}  # story: NLP has high drop-off; everything else uses DEFAULT_DROP_RATE
DEFAULT_DROP_RATE = 0.08
DIFFICULTY_OFFSET = {Difficulty.easy: 8, Difficulty.medium: 0, Difficulty.hard: -8}
TOPIC_OFFSET = {"SQL Joins": -26}  # story: most students fail SQL Joins
PAYMENT_FAILURE_REASONS = [
    "UPI transaction declined by bank",
    "Bank server timeout",
    "Card expired",
    "Insufficient funds",
    "OTP verification failed",
]


@dataclass
class SeedData:
    users: list[User] = field(default_factory=list)
    courses: list[Course] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)
    quizzes: list[Quiz] = field(default_factory=list)
    enrollments: list[Enrollment] = field(default_factory=list)
    attempts: list[QuizAttempt] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    logins: list[LoginEvent] = field(default_factory=list)

    def tables_in_insert_order(self):
        return [
            self.users,
            self.courses,
            self.modules,
            self.topics,
            self.quizzes,
            self.enrollments,
            self.attempts,
            self.payments,
            self.logins,
        ]


def _ist(now: datetime, days_ago: int, hour: int, minute: int) -> datetime:
    """A wall-clock time in India, `days_ago` days before `now`'s date."""
    day = now.astimezone(IST).date() - timedelta(days=days_ago)
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


def build_seed(now: datetime, seed: int = 42, n_students: int = 150) -> SeedData:
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)
    data = SeedData()
    ids = {
        name: itertools.count(1) for name in ("user", "course", "module", "topic", "quiz", "enr", "att", "pay", "login")
    }

    def add_user(name: str, email: str, role: Role, city: str, joined_days_ago: int) -> User:
        user = User(
            id=next(ids["user"]),
            full_name=name,
            email=email,
            role=role,
            city=city,
            joined_at=now - timedelta(days=joined_days_ago),
            is_active=True,
        )
        data.users.append(user)
        return user

    # ---- Staff ----
    add_user(*ADMIN[:2], Role.admin, ADMIN[2], 700)
    for name, email, city in SUPPORT:
        add_user(name, email, Role.support, city, rng.randint(300, 600))

    # ---- Courses, modules, topics, quizzes ----
    course_by_code: dict[str, Course] = {}
    topics_by_course: dict[str, list[Topic]] = {}
    quiz_by_topic: dict[int, Quiz] = {}
    created = now - timedelta(days=720)
    for spec in COURSES:
        t_name, t_email, t_city = spec["teacher"]
        teacher = add_user(t_name, t_email, Role.teacher, t_city, rng.randint(500, 700))
        course = Course(
            id=next(ids["course"]),
            code=spec["code"],
            title=spec["title"],
            description=spec["description"],
            teacher_id=teacher.id,
            price_inr=spec["price_inr"],
            created_at=created,
        )
        data.courses.append(course)
        course_by_code[course.code] = course
        topics_by_course[course.code] = []
        for m_pos, (m_title, topic_specs) in enumerate(spec["modules"], start=1):
            module = Module(id=next(ids["module"]), course_id=course.id, position=m_pos, title=m_title)
            data.modules.append(module)
            for t_pos, (t_title, diff) in enumerate(topic_specs, start=1):
                topic = Topic(
                    id=next(ids["topic"]),
                    module_id=module.id,
                    position=t_pos,
                    name=t_title,
                    difficulty=Difficulty(diff),
                )
                data.topics.append(topic)
                topics_by_course[course.code].append(topic)
                quiz = Quiz(
                    id=next(ids["quiz"]),
                    topic_id=topic.id,
                    title=f"{t_title} Quiz",
                    created_at=created + timedelta(days=10),
                )
                data.quizzes.append(quiz)
                quiz_by_topic[topic.id] = quiz

    # ---- Students ----
    story = {key: add_user(n, e, Role.student, c, 200) for key, (n, e, c, _) in STORY_STUDENTS.items()}
    story_names = {u.full_name for u in story.values()}
    random_students: list[User] = []
    while len(story) + len(random_students) < n_students:
        first, last = fake.first_name(), fake.last_name()
        name = f"{first} {last}"
        if name in story_names:
            continue
        slug = re.sub(r"[^a-z.]", "", f"{first}.{last}".lower())
        user_id_preview = len(data.users) + 1
        email = f"{slug}{user_id_preview}@student.lmsdemo.in"
        random_students.append(add_user(name, email, Role.student, rng.choice(CITIES), rng.randint(20, 420)))

    # ---- Enrollments (+ their successful payment) ----
    def enroll(student: User, code: str, status: EnrollmentStatus, progress: int, enrolled_at: datetime) -> Enrollment:
        enr = Enrollment(
            id=next(ids["enr"]),
            student_id=student.id,
            course_id=course_by_code[code].id,
            enrolled_at=enrolled_at,
            status=status,
            progress_pct=progress,
        )
        data.enrollments.append(enr)
        return enr

    def pay(student: User, code: str, status: PaymentStatus, at: datetime, reason: str | None = None) -> None:
        price = course_by_code[code].price_inr
        amount = price if rng.random() > 0.3 else int(round(price * 0.8, -2) - 1)  # 30% used a discount
        method = rng.choices(list(PaymentMethod), weights=[55, 25, 15, 5])[0]
        data.payments.append(
            Payment(
                id=next(ids["pay"]),
                student_id=student.id,
                course_id=course_by_code[code].id,
                amount_inr=amount,
                status=status,
                method=method,
                failure_reason=reason,
                created_at=at,
            )
        )

    story_progress = {
        "riya": {"PY101": 100, "ML201": 80, "DL301": 60},
        "ananya": {"PY101": 100, "ML201": 100, "DL301": 85, "NLP302": 70},
        "arjun": {"DB201": 55, "DSA201": 40},
        "karan": {"PY101": 50, "DB201": 30},
    }
    for key, user in story.items():
        for i, code in enumerate(STORY_STUDENTS[key][3]):
            progress = story_progress[key][code]
            status = EnrollmentStatus.completed if progress == 100 else EnrollmentStatus.active
            at = now - timedelta(days=190 - i * 20)
            enroll(user, code, status, progress, at)
            pay(user, code, PaymentStatus.success, at - timedelta(minutes=5))

    for student in random_students:
        codes = [c for c, p in COURSE_POPULARITY.items() if rng.random() < p] or ["PY101"]
        days_member = (now - student.joined_at).days
        for code in codes:
            enrolled_at = student.joined_at + timedelta(days=rng.uniform(0, days_member * 0.6))
            days_in = (now - enrolled_at).days
            if rng.random() < DROP_RATE.get(code, DEFAULT_DROP_RATE):
                status, progress = EnrollmentStatus.dropped, rng.randint(5, 40)
            elif rng.random() < (0.35 if days_in > 120 else 0.05):
                status, progress = EnrollmentStatus.completed, 100
            else:
                status = EnrollmentStatus.active
                progress = max(5, min(95, int(days_in / 150 * 100 * rng.uniform(0.6, 1.2))))
            enroll(student, code, status, progress, enrolled_at)

            paid_at = enrolled_at - timedelta(minutes=rng.randint(2, 20))
            # Some old purchases needed a second try (all > 45 days ago, so the
            # "failed payments in the last 30 days" story stays exact).
            if enrolled_at < now - timedelta(days=45) and rng.random() < 0.06:
                pay(
                    student,
                    code,
                    PaymentStatus.failed,
                    paid_at - timedelta(minutes=10),
                    rng.choice(PAYMENT_FAILURE_REASONS),
                )
            refunded = status == EnrollmentStatus.dropped and rng.random() < 0.25
            pay(student, code, PaymentStatus.refunded if refunded else PaymentStatus.success, paid_at)

    # ---- Story: failed payments in the last 30 days (exactly 5 students) ----
    arjun = story["arjun"]
    pay(arjun, "DL301", PaymentStatus.failed, _ist(now, 3, 19, 42), "UPI transaction declined by bank")
    pay(arjun, "DL301", PaymentStatus.failed, _ist(now, 2, 11, 5), "Bank server timeout")
    enrolled_course_ids: dict[int, set[int]] = {}
    for enr in data.enrollments:
        enrolled_course_ids.setdefault(enr.student_id, set()).add(enr.course_id)
    unlucky = rng.sample(random_students, 6)
    for i, student in enumerate(unlucky):
        not_enrolled = [c for c in COURSE_POPULARITY if course_by_code[c].id not in enrolled_course_ids[student.id]]
        code = rng.choice(not_enrolled)
        if i < 4:  # 4 more students with a failed payment -> 5 in total with Arjun
            pay(
                student,
                code,
                PaymentStatus.failed,
                _ist(now, rng.randint(1, 28), rng.randint(9, 22), rng.randint(0, 59)),
                rng.choice(PAYMENT_FAILURE_REASONS),
            )
        else:  # 2 pending payments from the last 2 days
            pay(
                student,
                code,
                PaymentStatus.pending,
                _ist(now, rng.randint(1, 2), rng.randint(8, 11), rng.randint(0, 59)),
            )

    # ---- Quiz attempts ----
    # Random students are capped at 84 so Ananya (96) is clearly the top performer.
    ability = {u.id: max(40.0, min(84.0, rng.gauss(68, 10))) for u in random_students}
    ability |= {story["riya"].id: 74.0, story["ananya"].id: 96.0, story["arjun"].id: 62.0, story["karan"].id: 58.0}
    noise_sd = {story["ananya"].id: 3.0}
    riya_weak = {"Backpropagation": (25, 38), "Chain Rule": (30, 42)}
    story_ids = {u.id for u in story.values()}
    code_by_course_id = {c.id: c.code for c in data.courses}

    def clamp(x: float) -> int:
        return int(max(0, min(100, round(x))))

    for enr in data.enrollments:
        topics = topics_by_course[code_by_course_id[enr.course_id]]
        covered = round(len(topics) * enr.progress_pct / 100)
        span = (now - enr.enrolled_at) * 0.95
        for i, topic in enumerate(topics[:covered]):
            if enr.student_id not in story_ids and rng.random() > 0.9:
                continue  # skipped this quiz
            if enr.student_id == story["riya"].id and topic.name in riya_weak:
                score = rng.randint(*riya_weak[topic.name])
            else:
                score = clamp(
                    ability[enr.student_id]
                    + DIFFICULTY_OFFSET[topic.difficulty]
                    + TOPIC_OFFSET.get(topic.name, 0)
                    + rng.gauss(0, noise_sd.get(enr.student_id, 9.0))
                )
            at = enr.enrolled_at + span * ((i + rng.random()) / max(covered, 1))
            quiz_id = quiz_by_topic[topic.id].id
            data.attempts.append(
                QuizAttempt(
                    id=next(ids["att"]),
                    quiz_id=quiz_id,
                    student_id=enr.student_id,
                    attempted_at=at,
                    score_pct=score,
                    time_taken_sec=rng.randint(180, 900),
                )
            )
            if rng.random() < (0.25 if score < 60 else 0.08):  # retake
                if enr.student_id == story["riya"].id and topic.name in riya_weak:
                    retake = rng.randint(*riya_weak[topic.name])
                else:
                    retake = min(100, score + rng.randint(3, 15))
                retake_at = min(at + timedelta(days=rng.randint(1, 5)), now - timedelta(hours=1))
                data.attempts.append(
                    QuizAttempt(
                        id=next(ids["att"]),
                        quiz_id=quiz_id,
                        student_id=enr.student_id,
                        attempted_at=retake_at,
                        score_pct=retake,
                        time_taken_sec=rng.randint(180, 900),
                    )
                )

    # ---- Login events (last 60 days) ----
    karan = story["karan"]
    devices, device_weights = ["web", "android", "ios"], [50, 40, 10]
    for user in data.users:
        count = rng.randint(20, 50) if user.role != Role.student else rng.randint(4, 40)
        newest = 2 if user.id == karan.id else 0  # Karan hasn't logged in successfully since the lockout
        for _ in range(count):
            at = _ist(now, rng.randint(newest, 60), rng.randint(7, 23), rng.randint(0, 59))
            if at > now:
                continue
            failed = rng.random() < 0.03
            data.logins.append(
                LoginEvent(
                    id=next(ids["login"]),
                    user_id=user.id,
                    occurred_at=at,
                    success=not failed,
                    failure_reason="wrong_password" if failed else None,
                    device=rng.choices(devices, weights=device_weights)[0],
                )
            )
    # Story: Karan locked out yesterday — 4 wrong passwords, then 2 "account_locked".
    for i, reason in enumerate(["wrong_password"] * 4 + ["account_locked"] * 2):
        data.logins.append(
            LoginEvent(
                id=next(ids["login"]),
                user_id=karan.id,
                occurred_at=_ist(now, 1, 9, 10 + i * 6),
                success=False,
                failure_reason=reason,
                device="android",
            )
        )

    return data
