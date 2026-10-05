# LMS GenAI: project plan

An AI learning assistant for an LMS. It answers from course material with citations,
knows how concepts connect, lets staff query data in plain English, and hands over
to a human with full context when it isn't sure.

**Goal of the project: learn GenAI.** About 80% of the effort goes into GenAI concepts and
20% into frontend/backend/DB plumbing.

---

## Decisions

| Area | Choice |
|---|---|
| LLM | OpenAI: small model for everything (`gpt-4o-mini` by default, set in `.env`), `text-embedding-3-small` |
| Backend | Python 3.12, FastAPI, `uv` |
| GenAI libraries | LangChain (steps kept visible, no black-box chains), LangGraph from Phase 4 |
| Frontend | Next.js + Tailwind, kept minimal |
| Relational DB | PostgreSQL (Docker) |
| Vector DB | Qdrant (Docker) |
| Graph DB | Neo4j Community (Docker) |
| Tracing | Langfuse Cloud, free plan (US region) |
| Login | Dummy login (pick a user). Permissions enforced in 3 layers |
| Machine | Windows, 8 GB RAM: databases in Docker, app runs natively |
| Cost guard | Daily app budget $1 + OpenAI account limit |

---

## Phases

Each phase ends with something you can run, learning notes in `docs/phase-N.md`, and
a pause so you can understand it before the next one.

| # | Phase | GenAI concepts learned | Done when |
|---|---|---|---|
| 0 ✅ | **Skeleton** | Tokens & cost, LLM error handling (retry, backoff, circuit breaker, budget), tracing, "LLM is not a security boundary" | Each role logs in to its portal; first LLM call shows tokens/cost/latency in the UI and in Langfuse |
| 1 ✅ | **Upload pipeline + basic RAG** | Parsing (keeping page numbers), chunking strategies, overlap, embeddings, cosine similarity, vector DB payloads, top-k, grounded prompts, streaming (SSE). Generated course files; start the 20-question eval set | A student gets a correct streamed answer from an uploaded PDF |
| 2 ✅ | **Better retrieval** | Metadata filtering, query rewriting, hybrid search (dense + sparse, RRF), reranking, citations, relevance grading + corrective retry. Measure recall@k / MRR before & after | Answers cite file + page; students only see enrolled courses; numbers show the gain |
| 3 | **Concept graph + learning paths** | Structured extraction (JSON schema + validation), entity dedup, graph modelling, Cypher traversal, GraphRAG-lite, quiz generation, human approval | "I don't understand X" returns a sensible study order from approved concepts |
| 4 | **Routing + agent** | Intent routing (rules vs embeddings vs LLM), tool calling, LangGraph state machine, short/long-term memory, confidence scoring | Each question goes to the right tool; decisions visible in traces |
| 5 | **Tickets + feedback loop** | Human in the loop, context packaging, knowledge feedback, clustering questions with embeddings | A resolved ticket's answer is used by the AI next time |
| 6 | **SQL agent (all roles, scoped)** | Schema-aware prompting, few-shot, self-correction loop, SELECT-only validation, read-only DB user, row-level security, chart choice | Plain English → SQL → answer + chart; can't write; can't escape scope |
| 7 | **Evaluation, guardrails, tracing** | RAG metrics (context precision/recall, faithfulness, relevance), LLM-as-judge and its biases, injection & off-topic guardrails, cost/latency dashboards | One command runs the eval and shows better/worse |

**Phase 1 note:** the enrolled-course filter on retrieval is already in Phase 1, because it is a
**security** rule (students must never see other courses' material), not a feature. Phase 2 adds the
user-facing filters (module, file type) on top of it.

**Phase 2 note:** "answer grading" became *retrieval* grading: the reranker score decides whether any
chunk is relevant, and if none is, a corrective retry rephrases the query once (CRAG-style). Grading the
*answer* itself (faithfulness, with an LLM judge) needs an eval harness and belongs in Phase 7. The
file-type filter was dropped: one course's material is rarely split by file type, while course and
module filters match how students think.

**File types:** `.doc` (old binary Word) is rejected with a "save as .docx" message; scanned PDFs (no
text layer) are rejected with an OCR hint. Both are deliberate scope limits.

---

## Features by portal

⭐ = core (build first). Others are extras if time allows.

### Student

| # | Feature | Phase |
|---|---|---|
| S1 ⭐ | Ask a doubt → streamed answer | 1 |
| S2 ⭐ | Citations (file + page) under each answer | 2 |
| S3 ⭐ | Answers only from enrolled courses | 2 |
| S4 ⭐ | Follow-up questions work (query rewriting) | 2 |
| S5 | Filter chat by course / module / file type | 2 |
| S6 ⭐ | 👍/👎 per answer; 👎 creates a ticket | 5 |
| S7 | "Not sure" warning when confidence is low | 4 |
| S8 | Off-topic questions politely refused | 7 |
| S9 ⭐ | "I don't understand X" → learning path | 3 |
| S10 | Each path step links to its material | 3 |
| S11 | Known prerequisites marked done (from quiz scores) | 4 |
| S12 ⭐ | Assistant remembers weak topics | 4 |
| S13 ⭐ | Practice questions from weak topics | 4 |
| S14 | Practice answers graded with explanation | 4 |
| S15 | Take teacher-approved quizzes | 3 |
| S16 | Ask about own data in plain English | 6 |
| S17 ⭐ | Other people's data is blocked | 0 / 6 |
| S18 ⭐ | Login/payment issues → ticket | 4 / 5 |
| S19 | See my tickets and status | 5 |

### Teacher

| # | Feature | Phase |
|---|---|---|
| T1 ⭐ | Upload HTML, DOC, PDF, TXT to course/module | 1 |
| T2 ⭐ | Processing status per file | 1 |
| T3 ⭐ | Auto tags (topic, difficulty, type), editable | 1 |
| T4 | Preview a file's chunks | 1 |
| T5 | Delete/replace a file (vectors + concepts cleaned up) | 1 |
| T6 ⭐ | LLM extracts concepts + prerequisites | 3 |
| T7 ⭐ | Review: approve / edit / merge / reject | 3 |
| T8 ⭐ | Publish approved concepts only | 3 |
| T9 | Visual graph view | 3 |
| T10 ⭐ | Generate quiz from file/topic | 3 |
| T11 ⭐ | Approve/edit quiz questions (with source chunk) | 3 |
| T12 | Quiz results for own courses | 6 |
| T13 ⭐ | Most asked doubts, grouped by meaning | 5 |
| T14 ⭐ | Content gaps: questions the AI couldn't answer | 5 |
| T15 | Ask about own students in plain English | 6 |
| T16 | Struggling students list | 4 / 6 |

### Support

| # | Feature | Phase |
|---|---|---|
| P1 ⭐ | Ticket queue (filters) | 5 |
| P2 ⭐ | Auto tickets: low confidence, 👎, non-academic | 5 |
| P3 ⭐ | Full context: question, rewritten query, chunks, AI draft, confidence, student & course | 5 |
| P4 ⭐ | Edit draft and resolve | 5 |
| P5 ⭐ | Resolved answer → knowledge base (FAQ collection) | 5 |
| P6 | "Don't save to KB" for private/one-off issues | 5 |
| P7 | Similar past tickets | 5 |
| P8 | Data scope: only the ticket's student | 0 / 6 |

### Admin

| # | Feature | Phase |
|---|---|---|
| A1 ⭐ | Plain English → answer + chart + SQL | 6 |
| A2 ⭐ | SQL agent fixes its own errors | 6 |
| A3 ⭐ | Read-only DB user, SELECT only | 6 |
| A4 ⭐ | Token cost dashboard | 7 |
| A5 ⭐ | Latency dashboard | 7 |
| A6 ⭐ | Quality dashboard (eval scores, 👍/👎, groundedness) | 7 |
| A7 | Trace viewer links | 7 |
| A8 | Run eval set and compare versions | 7 |
| A9 | Guardrail log | 7 |
| A10 | Full data scope | 0 |

---

## Permission matrix

Code: `backend/app/permissions.py` (single source of truth).

| Data | Student | Teacher | Admin | Support |
|---|---|---|---|---|
| Student records (profile, enrollments, scores) | Own only | Students of own courses | All | Only the ticket's student |
| Course material | Enrolled courses | Own courses | All | All |
| Payments | Own only | None | All | Only the ticket's student |
| AI usage dashboard | None | None | All | None |

### Three layers

| Layer | What it does | Can a clever prompt break it? |
|---|---|---|
| 1. Prompt / router | LLM politely refuses out-of-scope questions | Yes (soft layer, for UX only) |
| 2. Tools per role | A role's agent never receives tools it may not use | No |
| 3. Database | Queries filtered by scope (Phase 0: WHERE clauses; Phase 6: Postgres row-level security) | No |

Attack questions for testing these: `evals/attack_questions.yaml`.

---

## Error handling for LLM calls

| Situation | Behaviour |
|---|---|
| Temporary (timeout, network, 5xx, rate limit) | Retry up to 3 times with backoff 1s → 2s → 4s (+ jitter, respects Retry-After), then stop |
| Permanent (bad key, no credit/quota, unknown model, bad request) | No retry, stop immediately |
| Rate limit vs quota (both HTTP 429) | Quota detected from the error body and never retried |
| 5 consecutive failures | Circuit breaker pauses calls for 60s |
| Agent loops | Fixed max steps, then escalate to a human |
| Output length | Every call has a max-tokens limit |
| Daily budget | `llm_usage` table summed per day; calls refused at `DAILY_BUDGET_USD` |
| Langfuse down | Tracing skipped silently; the app keeps working |

---

## Seed data

1 admin, 2 support, 6 teachers, 150 students (Indian names), 6 courses × 4 modules,
64 topics, ~400 enrollments, ~2,800 quiz attempts, payments, login events. Fixed
random seed. Planted stories with verification SQL: `data/seed_stories.md`.

---

## Repository layout

```
backend/            FastAPI app (uv project)
  app/
    config.py       all settings (from .env)
    models.py       Postgres tables
    permissions.py  permission matrix
    scopes.py       permission matrix -> SQL filters
    auth.py         dummy login
    llm/            the one door to the LLM: chat, streaming, embeddings + retry, breaker, budget, tracing
    prompts/        every prompt, one file per feature
    ingest/         parse -> chunk -> embed -> tag -> index (Phase 1); reindex (Phase 2)
    rag/            Qdrant access, BM25 vectors, RRF, reranker, query rewriting, retriever (Phase 1-2)
    evals/          retrieval eval (python -m app.evals.retrieval [--compare])
    routers/        API endpoints
    seed/           dummy data (python -m app.seed --reset)
  scripts/          generate_course_files.py (renders data/course_source -> data/course_files)
  tests/
frontend/           Next.js app (login + 4 portals)
data/
  course_source/    course content as markdown (64 topics, with prerequisites)
  course_files/     the same content as 6 PDF, 6 DOCX, 6 HTML, 6 TXT files
  seed_stories.md   planted facts in the seed data
evals/              attack questions, retrieval questions
docs/               learning notes per phase
docker-compose.yml  Postgres, Qdrant, Neo4j
```
