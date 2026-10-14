# LMS GenAI

An AI learning assistant for an LMS, built phase by phase to **learn GenAI**: RAG, vector and
graph databases, query rewriting and routing, agents, human-in-the-loop, evaluation,
guardrails and tracing.

- What we're building and why: [PLAN.md](PLAN.md)
- What you learn in each phase: [docs/](docs/) (start with [docs/phase-0.md](docs/phase-0.md); Phase 3: [docs/phase-3.md](docs/phase-3.md))
- The planted "stories" in the dummy data: [data/seed_stories.md](data/seed_stories.md)
- Interview prep per phase (approach, alternatives, cross-questions): [docs/interview/](docs/interview/)

**Current phase: 3 (concept graph and quizzes), done.** After a file is indexed, an LLM extracts its key
concepts and prerequisites with structured output, every concept is checked against a quote from the file,
duplicates are merged across files, and the result goes into Neo4j as **drafts**. Teachers review them on the
**Concept graph** page (approve, edit, merge, reject, fix prerequisites); students type *"I don't understand
X"* on **Learning path** and get a study order of approved concepts, each linked to its file and page.
Teachers also generate **quizzes** from a file or topic: every question is checked against a quote from
its source passage, and the teacher approves each one before publishing. Measured with
`uv run python -m app.evals.concepts`. Phase 4 (routing, agent, MCP) comes next.

**Phase 2 (better retrieval):** hybrid search (meaning + BM25 keywords, fused with RRF), a local
cross-encoder reranker, follow-up questions (query rewriting), a corrective retry, "Search in" filters, and
a "Show details" panel that shows how each answer was found. Every step is measured with
`uv run python -m app.evals.retrieval --compare`.
Phase 1 gave us the upload pipeline and basic RAG; Phase 0 the dummy login, portals, seed data and a safe
LLM gateway (retries, circuit breaker, daily budget, Langfuse).

**Upgrading from Phase 2?** Pull, start Neo4j (`docker compose up -d`), then (from `backend/`):

```powershell
uv run uvicorn app.main:app --reload --port 8000   # adds the new columns; Ctrl+C after it starts
uv run python -m app.graph.backfill                # ONE time: concepts for the files you already have (~$0.05)
uv run python -m app.evals.concepts --show         # how close the graph is to the authors' prerequisites
```

**Upgrading from Phase 1?** Pull, then (from `backend/`):

```powershell
uv sync                                    # adds fastembed (reranker) and the stemmer
uv run python -m app.ingest.reindex        # ONE time: rebuild the index with keyword vectors (~$0.001)
uv run uvicorn app.main:app --reload --port 8000   # new DB columns are added automatically
uv run python -m app.evals.retrieval --compare     # Phase 1 vs every Phase 2 step
```

The first start downloads the reranker model (~80 MB) into `backend/storage/models/`. Until it is there
(or if the download fails) answers still work, just without reranking; `/health` shows `"reranker"`.

---

## Setup on Windows (PowerShell)

### 0. One-time prerequisites

| Tool | Check | Notes |
|---|---|---|
| Docker Desktop | `docker --version` | Must be running (whale icon in the tray) |
| Python 3.12 | `py -3.12 --version` | `uv` can also download it for you |
| uv | `uv --version` | Install: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Node.js 20+ | `node --version` | |
| Git | `git --version` | |

**Limit WSL memory to 4 GB** (keeps Windows usable on 8 GB of RAM). Create or edit
`C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
memory=4GB
processors=2
swap=2GB
```

Then run `wsl --shutdown` and restart Docker Desktop.

### 1. Get the code

Use a short path **outside OneDrive** (OneDrive syncing breaks Docker volumes and `node_modules`).

```powershell
mkdir C:\dev -Force; cd C:\dev
git clone https://github.com/pattjoshi/lms-genAI.git
cd lms-genAI
git checkout claude/llm-genai
```

### 2. Add your keys

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`. Keep
`LANGFUSE_BASE_URL=https://us.cloud.langfuse.com`. **Never commit `.env`** (it's in `.gitignore`).

### 3. Start the databases

```powershell
docker compose up -d
docker compose ps        # wait until all 3 are "running" (Neo4j takes ~30s the first time)
```

Admin UIs: Qdrant <http://localhost:6333/dashboard>, Neo4j <http://localhost:7474>
(user `neo4j`, password from `.env`).

### 4. Backend (terminal 1)

```powershell
cd backend
uv sync                                  # creates .venv and installs everything
uv run pytest                            # 97 tests; 5 use Neo4j and are skipped when it isn't running
uv run python -m app.seed --reset        # create tables + load dummy data
uv run python -m app.ingest.load_samples # index the 24 sample files + extract their concepts (~$0.05)
uv run uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs> · health check: <http://localhost:8000/health>

### 5. Frontend (terminal 2)

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>.

### 6. Try it

1. On the login page all 5 status dots should be green (Postgres, Qdrant, Neo4j, OpenAI key, Langfuse).
2. Log in as **Riya Sharma**: her weakest topics are Backpropagation and Chain Rule.
3. Click **Send** in "AI connection test": you get a reply plus tokens, cost, latency and attempts.
4. Click **Run request** in the permission test: refused (students can't list students).
5. Log out and log in as **Rahul Gupta** (teacher): the same request returns only his DBMS students.
6. Log in as **Neha Kapoor** (admin): the request returns all 150 students, and "AI usage today" shows your call.
7. Open your Langfuse project → **Traces**: your call is there, tagged `hello` and `student`.

**Phase 1:**

8. As **Riya**, open **Ask a doubt** and ask *"How does backpropagation compute gradients?"*. The answer
   streams in with numbered sources (file, page/section, similarity score) plus tokens, cost and latency.
9. Ask *"Who won the cricket world cup in 2011?"*: "I couldn't find this…". The LLM is never called.
10. Ask *"Explain the attention mechanism"*: Riya isn't enrolled in NLP, so she gets no NLP material.
11. As **Rahul Gupta**, open **Course files**: upload a file, watch it go parsing → … → ready, then click
    the eye icon to see exactly what the AI sees (chunks + topic tags).
12. In Langfuse, open the `rag_answer` trace: retrieve → generate, with the chunks and the full prompt.
13. Measure retrieval: `uv run python -m app.evals.retrieval` (from `backend/`).

**Phase 2:**

14. As **Riya**, click **Show details**, then ask *"What is the chain rule?"* and follow up with
    *"Can you show me a worked example?"*. The details panel says the follow-up was rewritten using the
    chat, and shows each source's meaning rank, keyword rank, cosine and reranker score. **New chat** forgets
    the context.
15. Ask *"dying ReLU"* (a keyword question) and compare the meaning vs keyword ranks in the panel.
16. Use **Search in** to limit a question to one course or module.
17. Click a citation number like **1** in an answer: it jumps to that source.
18. Run `uv run python -m app.evals.retrieval --compare` and read the table: which step fixed which questions?

**Phase 3:**

19. As **Rahul Gupta**, open **Course files**: the new **Concepts** column shows how many draft concepts each
    file produced. Click it to see each concept with its definition, prerequisites ("Learn first") and the
    sentence it was found in.
20. Open Neo4j (<http://localhost:7474>) and run `MATCH p=(:Concept)-[:REQUIRES*1..3]->() RETURN p LIMIT 100`.
21. Run `uv run python -m app.evals.concepts --show` and read which topics or prerequisites were missed.
22. As **Riya**, open **Learning path** and search *backpropagation*: nothing yet, because no concept is approved.
23. As **Suresh Rao** (DL301 teacher), open **Concept graph**: preview a path (route icon), reject or merge
    what's wrong, then **Approve all drafts**. Do the same for ML201 as **Neha Kapoor** (admin).
24. As **Riya** again: the path for *backprop* lists the prerequisites first, each with its file and page.
    Steps DL301 only mentions point to ML201. On her dashboard, each weak topic has a **study path** link.
25. As **Suresh Rao**, open **Quizzes**, generate 5 questions from a DL301 file, check each one against its
    source passage, approve or reject them all and **Publish**.
26. As **Riya**, open **Quizzes**, take it, and submit with one wrong answer: each result shows the
    explanation and the file and page to read.

Then work through the experiments in [docs/phase-0.md](docs/phase-0.md), [docs/phase-1.md](docs/phase-1.md),
[docs/phase-2.md](docs/phase-2.md) and [docs/phase-3.md](docs/phase-3.md).

---

## Daily use

```powershell
docker compose up -d                                         # start databases
cd backend;  uv run uvicorn app.main:app --reload --port 8000  # terminal 1
cd frontend; npm run dev                                      # terminal 2
docker compose down                                          # stop databases (data kept)
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `npm : ... running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Port already in use (5433, 6333, 7474, 7687, 8000, 3000) | Find it: `netstat -ano \| findstr :8000`, then `taskkill /PID <pid> /F`, or change the port in `.env` |
| `docker compose` fails: cannot connect to Docker | Start Docker Desktop and wait until it says "running" |
| Login page: "Database tables are missing" | `uv run python -m app.seed --reset` (from `backend/`) |
| Login page: "Cannot reach the backend" | Is uvicorn running on port 8000? Check terminal 1 for errors |
| Neo4j dot red right after `docker compose up` | Wait 30–60s, refresh. Check `docker compose logs neo4j` |
| Neo4j `AuthError ... unauthorized` | Neo4j keeps the password from its **first** start. Reset it (empty in Phase 0–2): `docker compose rm -sf neo4j`, `docker volume rm lms-genai_neo4j_data`, `docker compose up -d neo4j` |
| Qdrant `Restarting (101)` / "Server disconnected" | Check `docker compose logs qdrant --tail 40`. Then reset it: `docker compose rm -sf qdrant`, `docker volume rm lms-genai_qdrant_data`, `docker compose up -d qdrant` |
| AI test: `invalid_api_key` | Wrong `OPENAI_API_KEY` in `.env`. Restart uvicorn after editing `.env` |
| AI test: `quota_exceeded` | OpenAI account out of credit or monthly limit hit |
| AI test: `model_not_found` | Your key can't use `OPENAI_CHAT_MODEL`. Pick another small model and update the prices in `.env` |
| AI test: `daily_budget_reached` | Today's spend hit `DAILY_BUDGET_USD`. Resets at midnight IST |
| AI test: `ai_paused` | Circuit breaker opened after repeated failures. Fix the cause; it retries after 60s |
| Langfuse dot red | Keys missing or wrong in `.env`. The app still works without tracing |
| Upload fails: `.doc` not supported | Save the file as `.docx` in Word (old binary .doc needs extra tools) |
| Upload `failed`: "No text found… scanned PDF" | The PDF is images only. OCR is out of scope; use a text PDF |
| File stuck in `embedding`/`failed` with an AI error | Fix the key/budget issue, then click **Re-process** (↻) on the file |
| Every answer says "I couldn't find this" | Did you run `load_samples`? Is Qdrant green? Is the student enrolled in that course? |
| Changed `CHUNK_SIZE`/`CHUNK_OVERLAP` | Re-index: `uv run python -m app.ingest.reindex --force` |
| Answer error `reindex_needed` / "index is in the Phase 1 format" | Run once: `uv run python -m app.ingest.reindex` (from `backend/`) |
| Details panel: "Reranker model could not be loaded" | First start needs internet to download the model (~80 MB, from Hugging Face). Check `/health` → `retrieval.reranker`; restart the backend once online. Answers work without it. Or set `RAG_RERANK=false` |
| Follow-ups not understood | Ask them in the same chat (not after **New chat**). `RAG_REWRITE=true` in `.env` |
| "Last 30 days" stories look wrong | Data dates are relative to when you seeded. Re-seed with `--reset` |
| Start completely fresh | `docker compose down -v`, `docker compose up -d`, re-seed |
