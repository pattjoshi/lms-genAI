# Phase 2: Better retrieval

**Goal:** find the right part of the notes more often, and **prove it with numbers**. Phase 1 used one
vector search. Phase 2 turns it into a small pipeline where every step can be switched off, so the eval
can show what each one is worth.

Your Phase 1 baseline (20 questions): **hit@1 0.80 · hit@3 0.85 · hit@5 0.90 · MRR 0.838 · no-answer 2/2.**
Read it like this: 4 questions miss the top spot, and 2 aren't in the top 5 at all. A reranker can only
reorder what search found, so the second problem needs better *search* (hybrid search, query rewriting),
and the first needs better *ranking* (the reranker).

---

## 1. The query pipeline, before and after

```
PHASE 1                                    PHASE 2
question ─▶ embed ─▶ top 5 by cosine       question
              │                              │
              ▼                              ├─ 1. follow-up? rewrite into a standalone question (LLM, uses this chat)
          ≥ 0.25? ─▶ answer                  ▼
                                             2. ONE Qdrant request, filtered to allowed courses (+ chosen course/module):
                                                ├─ meaning search  (dense vector, cosine)  top 20
                                                └─ keyword search  (BM25 sparse vector)    top 20
                                             3. fuse the two rankings with RRF
                                             4. rerank the candidates with a cross-encoder (local CPU)
                                             5. keep the best 5; relevant = reranker score ≥ 0.02
                                             │
                                             ├─ nothing relevant? 6. rephrase in textbook terms, search once more
                                             ▼
                                             grounded prompt with [1][2] ─▶ LLM ─▶ stream
```

| Step | File | What to read for |
|---|---|---|
| Keyword vectors | `backend/app/rag/sparse.py` | tokenising, stemming, BM25 weights, hashing words to ids |
| Fusion | `backend/app/rag/fusion.py` | Reciprocal Rank Fusion in 6 lines |
| Reranker | `backend/app/rag/reranker.py` | bi-encoder vs cross-encoder, lazy load, graceful fallback |
| Rewriting | `backend/app/rag/rewrite.py`, `prompts/rewrite.py` | follow-up rewrite, corrective rewrite, output cleaning |
| Pipeline | `backend/app/rag/retriever.py` | the 6 steps, `RetrievalOptions`, relevance gate (`mark_used`) |
| Vector DB | `backend/app/rag/vectorstore.py` | named vectors, sparse vectors with IDF, batch query, format check |
| Chat | `backend/app/routers/chat.py` | conversation history from the DB, filters, details event |
| Re-index | `backend/app/ingest/reindex.py` | rebuilding an index after a format change |
| Eval | `backend/app/evals/retrieval.py`, `evals/retrieval_questions.yaml` | modes, `--compare`, categories, threshold check |

---

## 2. Concepts

### 2.1 Why vector search alone misses things

Embeddings compare **meaning**. That is great for *"why does my model do great on training data but badly
on new data?"* → overfitting. It is weak on **exact tokens**: `pd.merge`, `__init__`, `EXPLAIN ANALYZE`,
`RLHF`, an error name like `RecursionError`. Those strings are rare, carry a lot of meaning for a human,
but an embedding model blurs them into "something about Python/SQL". Students copy exactly these strings
from code, slides and error messages.

Keyword search (BM25) is the opposite: exact on rare tokens, blind to synonyms. Using **both** covers each
one's blind spot. That is **hybrid search**.

### 2.2 BM25 as a sparse vector

A dense vector has 1,536 numbers, all non-zero. A **sparse** vector has one slot per possible word, which is
millions of slots, but only the words in the text are non-zero, so we store `{word_id: weight}` pairs.

- **Tokenise:** lower-case; keep `pd.merge`, `k-means`, `read_csv`, `__init__` whole **and** add their parts
  (`pd`, `merge`); drop stop words ("the", "is"); stem plain words ("joins" → "join").
- **Word id:** `crc32(word)`. A *stable* hash: Python's `hash()` changes on every run, which would silently
  break the index on restart.
- **Document weight** (BM25's term-frequency part): `tf·(k1+1) / (tf + k1·(1 − b + b·len/avg_len))`.
  The 2nd mention of a word counts less than the 1st (k1 = 1.2, *saturation*), and long chunks are
  penalised (b = 0.75), so a long chunk doesn't win just by containing more words.
- **IDF** (rare words matter more) is computed **by Qdrant at query time** (`Modifier.IDF`) over the whole
  collection. So uploading a new file never requires re-weighting the old ones.
- **Query weight:** 1 per distinct word.

This is what fastembed's `Qdrant/bm25` does; writing it out means no model download and every step is visible.

### 2.3 Reciprocal Rank Fusion (RRF)

The two searches return scores on different scales (cosine 0–1, BM25 0–∞). You can't add them. RRF ignores
the scores and uses **ranks**:

```
rrf(chunk) = Σ over lists  1 / (60 + rank)
```

A chunk at rank 2 in both lists (1/62 + 1/62 = 0.0323) beats a chunk at rank 1 in only one list (0.0164).
Agreement between two very different signals is strong evidence. k = 60 comes from the original paper and
flattens the gap between rank 1 and 2, so one over-confident list can't dominate.

### 2.4 Reranking: bi-encoder vs cross-encoder

| | Bi-encoder (embeddings) | Cross-encoder (reranker) |
|---|---|---|
| Input | question and chunk **separately** | question + chunk **together** |
| Chunk vectors | computed once, at upload | nothing to pre-compute |
| Cost per question | 1 embedding + a fast index lookup | one model run **per candidate** |
| Accuracy | good | better: it sees which words of the question match which words of the chunk |

So we use both: the cheap search narrows thousands of chunks to 20, and the accurate model orders those 20.
Our model, `ms-marco-MiniLM-L-6-v2` (~80 MB, ONNX, CPU), was trained on Bing search queries. It reranks
20 chunks in roughly 0.1–0.3 s on a laptop CPU.

It outputs a raw score (a logit, about −12 to +12); a sigmoid turns it into 0–1. Different scale from
cosine, so it gets its **own threshold**, `RAG_MIN_RERANK_SCORE`, and the eval prints a *threshold check*:
the lowest score of a correct chunk vs the highest score of an off-topic question. A threshold between the
two separates them.

**Graceful degradation:** if the model can't be loaded (no internet on first run, disk full), retrieval
continues **without** reranking, the details panel shows a warning, and `/health` says
`"reranker": "unavailable"`. A quality feature must never take answers down with it.

### 2.5 Follow-up questions: conversational query rewriting

*"Can you give an example?"* means nothing to a search engine. Each chat now has a `conversation_id` (made
by the browser, renewed by **New chat**). The server loads the last 3 doubts of that conversation **from
the database** (not from the browser, so a client can't inject a fake history), and a small LLM call turns
the follow-up into a standalone question: *"Can you give an example of the chain rule?"*.

- Only the **search** uses the rewrite. The answer prompt gets the standalone question *and* the student's
  own words; the UI shows "Understood as: …".
- No history → no LLM call (most questions cost nothing extra).
- If the rewrite call fails, we search with the original question and show a warning (degrade, don't fail).

### 2.6 Corrective retry (relevance grading, CRAG-style)

After reranking we already have a **relevance grade** for every chunk. If **none** passes, the student may
have described a concept without naming it (*"my model remembers the training data"*). One LLM call
rephrases it in textbook terms (*"overfitting regularization"*), we search once more and keep the result
only if it is relevant. **Once**, not in a loop: a loop is how cost and latency explode.

A truly off-topic question (*"capital of Australia"*) still ends in "I couldn't find this": the retry also
has to pass the relevance gate.

### 2.7 Filters: narrowing, never widening

"Search in DL301 → Module 2" adds a `course_id`/`module_id` condition **inside** the Qdrant search
(pre-filtering). The server intersects it with what the user may read: picking a module of a course you
aren't enrolled in returns nothing. The UI filter is a convenience; the security filter still comes from
identity.

### 2.8 Re-indexing after a format change

A Phase 1 collection has one unnamed vector per point and no room for keyword vectors, so it must be
rebuilt: `uv run python -m app.ingest.reindex`. The app detects the old format and says so (startup log,
answer error `reindex_needed`) instead of failing obscurely, and never deletes data on its own.

We drop and rebuild (search is empty for a minute). In production you'd build a **new** collection next to
the old one and switch a **collection alias** when it's ready: zero downtime and instant rollback.

### 2.9 Measuring each step

The eval set grew from 22 to 48 questions, in categories that each target a weakness:

| Category | Example | Step that should help |
|---|---|---|
| semantic (20) | "Why can't one perceptron solve XOR?" | (Phase 1 baseline) |
| keyword (12) | "EXPLAIN ANALYZE", "dying ReLU", "RLHF" | hybrid search |
| paraphrase (6) | "How can I squeeze 50 columns into 2 to plot them?" | reranking, corrective retry |
| follow_up (5) | after "What is a database index?": "Does it make anything slower?" | query rewriting |
| no_answer (5) | "How do I deploy my model on Kubernetes?" | relevance threshold |

`--compare` runs the same questions on the same index in 5 modes: `dense` (= Phase 1), `hybrid`,
`dense+rerank`, `hybrid+rerank`, `full` (+ rewrite + corrective). It prints one row per mode, per-category
hit@5, and **which questions changed rank**, which is more useful than the averages.

**Important:** the Phase 1 numbers came from 20 easy-ish questions. Compare modes on the **same** 48
questions (the `dense` row is your new baseline), not against the old 0.80.

---

## 3. Experiments: do these

Restart the backend after changing `.env`.

1. **The table.** `uv run python -m app.evals.retrieval --compare --save`. Fill in:

   | mode | hit@1 | hit@5 | MRR | keyword | paraphrase | follow_up | no-answer |
   |---|---|---|---|---|---|---|---|
   | dense (Phase 1) | | | | | | | |
   | hybrid | | | | | | | |
   | hybrid+rerank | | | | | | | |
   | full | | | | | | | |

   Which step helped which category? Did any step make a question **worse**? (Look at the rank table.)
2. **Threshold.** Read the threshold check under the `hybrid+rerank` row. Is `RAG_MIN_RERANK_SCORE=0.02`
   between the two groups? Move it and re-run: what breaks first?
3. **Candidates.** `RAG_CANDIDATES=10` vs `40`: does hit@5 change? What happens to the `avg ms` column?
4. **RRF k.** `RAG_RRF_K=10` vs `200` with `--mode hybrid`. Which questions move?
5. **Follow-ups live.** With **Show details** on, ask "What is the chain rule?", then "Can you show me an
   example?". Read *Searched for*. Press **New chat** and ask the follow-up again: what changes?
6. **Keywords live.** Ask "EXPLAIN ANALYZE" and compare the *meaning* and *keyword* ranks in the panel.
7. **Corrective retry.** Ask "my model remembers the training data but fails on new data" as Riya. Did the
   panel show a retry? Now ask "What is the capital of Australia?": the rewrite either returns it unchanged
   (no second search) or the second search finds nothing relevant. Either way, no answer. Why is that right?
8. **Degradation.** Set `RERANKER_MODEL=does-not/exist`, restart, ask a question. Answers still work; read the
   warning and `/health`. Put it back.
9. **Filters.** As Riya, choose *Search in → DL301 → M2* and ask about the chain rule (it's in M1). What happens?
10. **Trace.** In Langfuse open a `rag_answer` trace: `rewrite_followup` → `search` (with `rerank` inside) →
    `corrective_retry` → generation. Where does the time go?

---

## 4. Check yourself

1. Why can't you add a cosine score and a BM25 score together?
2. Why rerank only 20 candidates instead of every chunk?
3. Why does the reranker need its own threshold?
4. Why is the chat history loaded from the database and not sent by the browser?
5. Why is the corrective retry done once and not until something is found?
6. The keyword search finds a chunk for an off-topic question. Why doesn't it reach the LLM?
7. Your `full` mode is better on average but one question got worse. What do you do?

---

## 5. Next: Phase 3, concept graph and learning paths

An LLM extracts concepts and prerequisites from each file (structured output, validated), a teacher
approves them, they go into Neo4j, and "I don't understand X" returns a study order.

Interview prep for this phase: [interview/phase-2.md](interview/phase-2.md).
