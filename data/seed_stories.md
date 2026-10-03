# Planted stories in the seed data

The seed data is random **except** for these deliberate stories. They are the known
correct answers for later phases: the weak-topic memory (Phase 4), the teacher
dashboard (Phase 5), the SQL agent (Phase 6) and the eval set (Phase 7).

`backend/tests/test_seed.py` checks that every story still holds. The SQL below is also
a good starter set of question → SQL pairs for the Phase 6 SQL agent.

Run SQL yourself: `docker compose exec postgres psql -U lms -d lms`

---

### 1. Riya Sharma is weak in Backpropagation and Chain Rule

Riya is enrolled in PY101, ML201 and DL301. She does fine elsewhere (~70%), but her
Backpropagation (~31%) and Chain Rule (~39%) scores are low. Chain Rule is a prerequisite
of Backpropagation: exactly the case the Phase 3 learning path is built for.

```sql
SELECT t.name, ROUND(AVG(a.score_pct)) AS avg_score
FROM quiz_attempts a
JOIN users u   ON u.id = a.student_id
JOIN quizzes q ON q.id = a.quiz_id
JOIN topics t  ON t.id = q.topic_id
WHERE u.email = 'riya.sharma@student.lmsdemo.in'
GROUP BY t.name ORDER BY avg_score LIMIT 3;
```

### 2. Most students fail SQL Joins (DBMS)

"SQL Joins" is the hardest topic in the whole LMS: average ~35%, and ~89% of attempts
are below 50 (fail). Teacher Rahul Gupta (DB201) should see it as his top problem topic.

```sql
SELECT t.name, ROUND(AVG(a.score_pct)) AS avg_score,
       ROUND(100.0 * AVG((a.score_pct < 50)::int)) AS fail_pct
FROM quiz_attempts a
JOIN quizzes q ON q.id = a.quiz_id
JOIN topics t  ON t.id = q.topic_id
GROUP BY t.name ORDER BY avg_score LIMIT 3;
```

### 3. Ananya Iyer is the top performer

Ananya (PY101, ML201, DL301, NLP302) has the highest average quiz score (~96%).

```sql
SELECT u.full_name, ROUND(AVG(a.score_pct), 1) AS avg_score
FROM quiz_attempts a JOIN users u ON u.id = a.student_id
GROUP BY u.full_name ORDER BY avg_score DESC LIMIT 3;
```

### 4. Exactly 5 students had failed payments in the last 30 days

6 failed payments from 5 students. Arjun Mehta tried to buy Deep Learning (DL301) twice,
3 and 2 days ago, and both failed. He is the classic support ticket ("money gone?").
All other failed payments in the data are older than 45 days.

```sql
SELECT u.full_name, c.code, p.failure_reason, p.created_at::date
FROM payments p
JOIN users u   ON u.id = p.student_id
JOIN courses c ON c.id = p.course_id
WHERE p.status = 'failed' AND p.created_at >= now() - interval '30 days'
ORDER BY p.created_at;
```

### 5. NLP has the highest drop-off

About 36% of NLP302 enrollments are `dropped`; every other course is between 4% and 14%.

```sql
SELECT c.code, COUNT(*) AS enrolled,
       ROUND(100.0 * AVG((e.status = 'dropped')::int)) AS drop_pct
FROM enrollments e JOIN courses c ON c.id = e.course_id
GROUP BY c.code ORDER BY drop_pct DESC;
```

### 6. Karan Verma is locked out

Yesterday (India time) Karan had 6 failed logins: 4 × `wrong_password`, then 2 ×
`account_locked`. He hasn't logged in successfully since. Nobody else has 3 or more
failed logins on that day. A typical non-academic ticket for Phase 5.

```sql
SELECT u.full_name, COUNT(*) AS failed_logins
FROM login_events l JOIN users u ON u.id = l.user_id
WHERE NOT l.success
  AND (l.occurred_at AT TIME ZONE 'Asia/Kolkata')::date
      = (now() AT TIME ZONE 'Asia/Kolkata')::date - 1
GROUP BY u.full_name ORDER BY failed_logins DESC;
```

---

**Dates are relative to when you ran the seed.** If you seeded long ago, "last 30
days" and "yesterday" drift. Re-run `uv run python -m app.seed --reset` to refresh them.
