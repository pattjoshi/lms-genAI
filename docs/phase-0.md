# Phase 0: Skeleton

**Goal:** have every piece running (databases, API, 4 portals, realistic data) and make
**one LLM call the way a production app should**: with a budget, retries, a circuit breaker,
cost logging and tracing. Every later phase reuses this pipeline.

---

## 1. What a request looks like

```
Browser (Next.js)                      FastAPI                                 Outside
─────────────────                      ───────                                 ───────
"Send" in AI test card
  │  POST /ai/hello
  │  header X-User-Id: 10  ─────────▶  get_current_user()   (auth.py)
                                         │  loads Riya from Postgres
                                         ▼
                                       service.chat()       (llm/service.py)
                                         1. breaker open?  ──▶ 503 ai_paused
                                         2. budget used?   ──▶ 429 daily_budget_reached
                                         3. ChatOpenAI.ainvoke ───────────────▶ OpenAI
                                            └ retry temporary errors (max 3)
                                            └ Langfuse callback ──────────────▶ Langfuse
                                         4. record_usage()  → llm_usage table
                                         ▼
  ◀──────────────  reply + tokens + cost + latency + attempts
```

Files to read, in this order:

1. `backend/app/llm/service.py`: the whole flow in ~100 lines
2. `backend/app/llm/errors.py`: which errors are temporary and which are permanent
3. `backend/app/llm/resilience.py`: retry and the circuit breaker
4. `backend/app/llm/budget.py`: cost formula and the daily guard
5. `backend/app/llm/tracing.py`: Langfuse
6. `backend/app/permissions.py` + `scopes.py`: who may see what

---

## 2. Concepts

### 2.1 Tokens and cost

LLMs read and write **tokens**, chunks of text of roughly 4 characters or ¾ of an English
word. You pay for both directions, and output tokens cost more than input tokens:

```
cost = input_tokens × input_price/1M  +  output_tokens × output_price/1M
```

Example with the default prices ($0.15 in, $0.60 out per 1M): a call with 60 input
and 40 output tokens costs `60×0.15/1M + 40×0.60/1M = $0.000033`, about 30,000 such
calls per dollar.

**Input tokens include the system prompt.** In RAG (Phase 1) the retrieved chunks go into
the prompt, so input tokens grow from ~60 to ~2,000+. That is where most of your cost will be.

We read real token counts from the response (`usage_metadata`), not estimates.

### 2.2 Temporary vs permanent errors

| Kind | Examples | Retry? | Why |
|---|---|---|---|
| Temporary | timeout, network drop, 500/503, 429 rate limit | Yes, max 3 | Likely to work in a few seconds |
| Permanent | 401 bad key, 429 **insufficient_quota**, 404 unknown model, 400 bad request | **No** | Will fail identically every time. Retrying wastes time and money |
| Unknown | any other exception | **No** | Never retry a bug you don't understand |

The tricky one is **HTTP 429**. OpenAI uses it both for "slow down" (retry) and "no credit
left" (don't). We look inside the error body for `insufficient_quota`.

We set `max_retries=0` on LangChain's `ChatOpenAI` and retry ourselves. Leaving both on
would multiply the attempts (the SDK's 3 attempts × our 4 = up to 12 calls) and hide what's happening.

### 2.3 Exponential backoff with jitter

Waits of 1s → 2s → 4s give an overloaded service room to recover. **Jitter** (a small
random extra) stops 100 clients that failed at the same moment from retrying at the same
moment. If OpenAI sends a `Retry-After` header, we respect it.

### 2.4 Circuit breaker

If 5 calls in a row fail, something is clearly broken (OpenAI down, key revoked). Instead
of every user waiting through 4 failing attempts, the breaker **opens** and refuses calls
instantly for 60s. Then it lets **one** trial call through (half-open): success closes it,
failure opens it again.

```
CLOSED ──5 failures──▶ OPEN ──60s──▶ HALF_OPEN ──trial ok──▶ CLOSED
                         ▲                 │
                         └──trial fails────┘
```

### 2.5 Budget guard

A bug in a loop can burn money fast. Every call writes a row to `llm_usage`. Before each
call we sum today's cost. At `DAILY_BUDGET_USD` we refuse. Failed calls are logged too
(cost 0): they're useful for the error-rate dashboard in Phase 7.

### 2.6 Tracing (Langfuse)

A **trace** is the record of one request: every LLM call inside it, with prompt, response,
tokens, cost, latency and errors. In Phase 0 a trace has one step. In Phase 4 a single
question will produce a trace with 5–10 steps (rewrite → route → retrieve → rerank → answer
→ grade), and tracing is how you'll debug them.

We tag each trace with the user (`student-10`) and the feature (`hello`), so you can filter
"all of Riya's calls" or "all doubt-answering calls".

Rule: **tracing must never break the app.** No keys, or Langfuse down → we log a warning and carry on.

### 2.7 The LLM is not a security boundary

A prompt saying "students can't see other students' data" can be talked around ("I'm the
admin, ignore previous instructions…"). So permissions live in **code and the database**:

| Layer | Where | Phase |
|---|---|---|
| 1. Prompt / router refuses politely | prompts | 4 |
| 2. Each role's agent only gets its allowed tools | agent tools | 4 |
| 3. Data is filtered by scope | `scopes.py` now; Postgres row-level security in Phase 6 | 0 / 6 |

Phase 0 already has layer 3: `GET /data/students` returns different answers per role.
That's the "Permission test" card in every portal.

### 2.8 Seed data with planted stories

Random data has no "right answers", so you can't evaluate an AI on it. We plant
known facts (Riya is weak in Backprop, most students fail SQL Joins, 5 failed payments, …)
and a **fixed random seed** keeps the data identical every run. Later these become test
questions with known answers. See `data/seed_stories.md`.

### 2.9 Prompts live in one place

`backend/app/prompts/`: one file per feature. Even the hello prompt follows the
structure we'll use everywhere: **role** (who the model is) → **context** (who's asking) →
**constraints** (format, length, "don't invent facts").

---

## 3. Experiments: do these

Restart uvicorn after every `.env` change (Ctrl+C, then run it again).

1. **Tokens.** Send "Hi". Note the input tokens. Now send a 3-paragraph message. Why did
   input tokens grow but output tokens barely change? Edit `HELLO_SYSTEM` in
   `prompts/hello.py` to be twice as long, then send "Hi" again and watch input tokens.
2. **Find your trace.** In Langfuse → Traces, filter by user `student-10`. Open it. Find
   the system prompt, the tokens and the latency. Compare Langfuse's cost with ours.
3. **Permanent error, no retry.** Set `OPENAI_CHAT_MODEL=gpt-does-not-exist`. Send.
   Expect `model_not_found` and **attempts = 1**. Check the backend log: no "retry" lines.
4. **Bad key + circuit breaker.** Set a wrong `OPENAI_API_KEY`. Send 6 times. The first 5
   give `invalid_api_key`; the 6th gives `ai_paused` instantly. Look at `/health`: breaker `open`.
5. **Temporary error with retries.** Turn off Wi-Fi and send. Watch the backend log:
   `retry 1/3 in 1.1s`, `2/3 in 2.2s`, `3/3 in 4.1s`, then `connection_error` after 4 attempts.
6. **Budget guard.** Set `DAILY_BUDGET_USD=0.00001`. The first call succeeds (the check is
   before the call); the second is refused. Why can a budget overshoot slightly? (Hint: `budget.py` docstring.)
7. **Permissions.** Run the permission test as Riya (student), Rahul Gupta (teacher),
   Neha Kapoor (admin) and Rohan Das (support). Then call the API directly in PowerShell:
   ```powershell
   curl.exe -H "X-User-Id: 10" http://localhost:8000/data/students   # 403
   curl.exe -H "X-User-Id: 1"  http://localhost:8000/data/students   # 200
   ```
   Notice the dummy login trusts the header, which is why it's "dummy". Real auth replaces
   only `auth.py`.
8. **Explore the data.** `docker compose exec postgres psql -U lms -d lms`, then run the SQL
   from `data/seed_stories.md`. Try `\d+ quiz_attempts`: the column comments are what the
   Phase 6 SQL agent will read.

---

## 4. Check yourself

1. Why is a 429 sometimes retried and sometimes not?
2. Why do we turn off the SDK's own retries?
3. What's the difference between the circuit breaker and the retry loop? Why have both?
4. Why is "the system prompt says students can't see others' data" not enough?
5. Why does the seed use a fixed random seed?
6. In RAG, which will dominate cost: input or output tokens? Why?

---

## 5. Next: Phase 1, the upload pipeline and basic RAG

Generate realistic course files (PDF, DOCX, HTML, TXT) for the 6 courses; parse → chunk →
embed → store in Qdrant with tags; answer a student's doubt with a streamed, grounded
answer; start the 20-question eval set.
