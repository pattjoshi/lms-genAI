# Interview prep: Phase 1 (upload pipeline and basic RAG)

Same format as Phase 0: **approach → why → 2 alternatives → cross-questions → real-world example.**
RAG is the most common GenAI interview topic, so expect deep follow-ups here.

---

## 0. "Explain your RAG pipeline end to end" (60 seconds)

> "There are two pipelines. **Indexing** runs in the background when a teacher uploads a file: I parse it
> while keeping page numbers or headings, split it into ~1,000-character chunks with 150 characters of overlap
> that never cross a page, embed the chunks with OpenAI's text-embedding-3-small, tag each chunk with
> a topic (rule first, embeddings second), and store vectors plus metadata in Qdrant.
>
> **Querying** happens live: I embed the question, search Qdrant **filtered to the student's enrolled
> courses**, and drop chunks below a similarity threshold. If nothing is relevant I say 'I couldn't find
> this' without calling the LLM. Otherwise I send numbered excerpts with strict grounding rules and stream
> the answer over Server-Sent Events, with [1][2] citations mapped to file and page. A 20-question
> retrieval eval with hit@k and MRR gives me a baseline to measure every improvement against."

**Numbers to remember:**

| Fact | Value |
|---|---|
| Sample files / formats | 24 files: 6 each of PDF, DOCX, HTML, TXT |
| Chunks | ~129 (1000 chars, 150 overlap) |
| Embedding cost of all files | ~12,500 tokens ≈ $0.00025 |
| Vector size | 1,536 (text-embedding-3-small), cosine distance |
| Retrieval | top-k 5, min score 0.25 |
| Eval set | 20 labelled questions + 2 off-topic |
| Tests | 39 unit tests, no network needed |

---

## 1. Why RAG instead of fine-tuning?

**Approach used:** RAG: retrieve relevant course excerpts at question time and give them to the model.

**Why:** course material changes every semester. With RAG, a new upload is searchable in seconds,
answers can **cite their source**, and deleting a file removes its knowledge immediately. Fine-tuning
teaches *style and behaviour* well but is a poor way to inject *facts*: it can't cite, is slow to update,
and the model can still blend facts wrongly.

**Alternative 1: fine-tuning** on the course content.
- ✅ No retrieval latency; learns domain tone and format.
- ❌ Expensive to retrain on every change, no citations, still hallucinates, can't "forget" a deleted file.
- **I'd use it** to teach output format or tone, *combined* with RAG for facts.

**Alternative 2: long-context stuffing** (put all course files in the prompt).
- ✅ Simplest; no chunking or vector DB.
- ❌ Cost scales with total content on *every* question, accuracy drops when the relevant part sits in the middle of a huge context ("lost in the middle"), and it's slower.
- **I'd use it** for small, fixed document sets (one policy PDF).

**Cross-questions:**
- *"Can you combine them?"* Yes. Fine-tune for behaviour (answer style, refusal pattern) and use RAG for knowledge.
- *"When does RAG fail?"* When retrieval misses the right chunk, when the answer needs reasoning across
  many documents, or when the question is ambiguous. Each later phase targets one of these.

**Real-world example:** answer engines like Perplexity show numbered source links under every answer.
That's RAG with citations, and it's why users can check the answer instead of trusting it blindly.

---

## 2. How do you parse different file formats?

**Approach used:** one small parser per format (pypdf, python-docx, BeautifulSoup, plain text) that
returns **sections with their location** (page or heading). Repeated header/footer lines are stripped from PDFs.

**Alternative 1: a document-parsing library/service** (e.g. Unstructured, LlamaParse, Azure Document Intelligence).
- ✅ Handles tables, multi-column layouts, images and many more formats.
- ❌ Heavier dependency or paid API; less control; another place for data to go.

**Alternative 2: OCR / vision models** (Tesseract, or a multimodal LLM reading page images).
- ✅ Works on scanned PDFs, handwriting, diagrams.
- ❌ Slow, costly, can introduce OCR errors.
- **I'd add it** when teachers upload scanned notes.

**Cross-questions:**
- *"What's the hardest format?"* PDF. It stores positioned glyphs, not paragraphs, so you get broken lines,
  headers on every page, columns read in the wrong order, and tables as soup.
- *"How do you handle tables?"* DOCX tables are kept row by row as `a | b | c`. For complex PDFs I'd use a
  layout-aware parser and store tables as separate chunks (often converted to markdown).
- *"Why keep page numbers?"* Citations. A student, or an auditor, must be able to verify the answer.

**Real-world example:** in insurance and legal document Q&A, answers are useless without "clause 4.2, page
17", so pipelines invest heavily in layout-aware parsing before anything else.

---

## 3. What chunking strategy did you use, and how did you choose the size?

**Approach used:** recursive character splitting (paragraph → line → sentence → word), 1,000 characters
with 150 overlap, **within** each page or section, with the section heading prefixed to each chunk.

**Why:** these are short, well-structured teaching notes. ~250-token chunks hold one idea, the overlap keeps
sentences intact across boundaries, and never crossing a page keeps citations exact.

**Alternative 1: semantic chunking:** split where the embedding similarity between consecutive sentences drops.
- ✅ Chunks follow topic shifts in messy, unstructured text.
- ❌ Needs embeddings at chunking time (cost); chunk sizes become unpredictable.

**Alternative 2: structure-based / parent-child chunking:** index small chunks, but give the LLM the
larger parent section (or neighbouring chunks) once a small chunk matches.
- ✅ Precise matching *and* enough context for the answer.
- ❌ More storage and logic.
- **I'd add it** if answers miss context that sits just outside the matched chunk.

**Cross-questions:**
- *"Characters or tokens?"* Tokens are what the model and the cost see. Characters are simpler and roughly
  4:1 for English. For Hindi or code the ratio differs a lot, so I'd switch to a token-based splitter there.
- *"How do you pick the size?"* Empirically: change one thing, re-index, re-run the retrieval eval. I don't guess.
- *"What does overlap cost?"* About 15% more chunks and embedding tokens, and possibly duplicate content in the prompt.

**Real-world example:** teams often start with "500 tokens, 50 overlap" from a tutorial and get poor
answers on long technical manuals. Moving to section-aware chunks with parent-context retrieval is a common fix.

---

## 4. Which embedding model, and what matters when choosing one?

**Approach used:** OpenAI `text-embedding-3-small` (1,536 dimensions), cosine similarity.

**Why:** cheap, good quality for English, no GPU needed on an 8 GB laptop, same provider as the LLM.

**Alternative 1: a larger API model** (`text-embedding-3-large`, 3,072 dimensions). Better retrieval on hard
queries, at ~6× the cost and 2× the storage. The bigger model supports shortening its vectors to fewer
dimensions to save storage.

**Alternative 2: open-source models** (e.g. BGE, E5, GTE families) run locally or self-hosted.
- ✅ No per-token cost, data stays in-house, can be fine-tuned on your domain.
- ❌ You host and scale them; needs CPU/GPU capacity.

**Cross-questions:**
- *"Can you switch embedding models later?"* Only by **re-embedding everything**. Vectors from different models
  aren't comparable. Store the model name with the collection; switching means a new collection plus a backfill.
- *"Hindi questions on English notes?"* Use a multilingual embedding model, or translate the query first.
- *"Why cosine, not dot product?"* These embeddings are normalised, so cosine and dot product rank the same.
  Cosine is just the explicit, scale-free choice.

---

## 5. How does the vector database fit in, and how do you filter?

**Approach used:** Qdrant collection `course_chunks`; each point = vector + payload (course, module, file,
page, topic, text); payload indexes on filter fields; the course filter applied **inside** the search.

**Alternative 1: pgvector** in the existing Postgres. One database, SQL joins with metadata. Great up to
millions of vectors; fewer vector-specific features.

**Alternative 2: an in-memory library** (FAISS). Extremely fast and simple for prototypes, but no
persistence, metadata filtering or multi-user updates out of the box.

**Cross-questions:**
- *"Pre-filter vs post-filter?"* Post-filtering the top-5 can leave zero results if they're all from other
  courses. Pre-filtering searches only allowed points.
- *"What is HNSW?"* A graph-based approximate nearest-neighbour index. Search is ~logarithmic instead of comparing
  against every vector, at the cost of being *approximate* (it can occasionally miss a true neighbour).
- *"Why store the text in the payload *and* in Postgres?"* The payload makes search results self-contained (no
  second lookup). Postgres is the source of truth for preview and evals, and lets Qdrant be rebuilt from scratch.

---

## 6. How are chunks tagged with topic and difficulty?

**Approach used:** **rule first** (the section heading equals a topic name → score 1.0; for PDFs, headings
are recovered from reading order), **embeddings second** (most similar module topic), **human last**
(low-confidence tags are flagged in the teacher's preview).

**Alternative 1: an LLM classifier per chunk.** Most flexible (it can read nuance), but costs one call per chunk and isn't deterministic.

**Alternative 2: manual tagging by teachers.** Most accurate, but doesn't scale and teachers won't do it for every chunk.

**Cross-questions:**
- *"Why does tagging matter?"* Filters ("only Module 3"), analytics ("most doubts are about Backprop"), and
  later the concept graph and learning paths.
- *"How do you know tagging is good?"* Our sample notes have headings, so 111 of 129 chunks are tagged by the
  rule. For the rest I'd sample and check by hand, or build a small labelled set.

---

## 7. How do you decide not to answer?

**Approach used:** a cosine-similarity threshold (`RAG_MIN_SCORE=0.25`). If no chunk passes it, return a fixed
"I couldn't find this in your course material" **without calling the LLM**, and log it as `no_context`.

**Alternative 1: always answer.** Higher apparent "helpfulness", but the model fills gaps from general knowledge, which is wrong for a course assistant.

**Alternative 2: let an LLM judge** relevance or answerability before or after generating. More accurate
than a raw threshold, but costs an extra call. (Phase 2 adds answer grading for this reason.)

**Cross-questions:**
- *"How do you pick the threshold?"* From the eval: look at the score distribution of correct matches vs
  off-topic questions and put the line in the gap. Re-check whenever the embedding model changes, because
  scores aren't calibrated across models.
- *"What's the cost of a wrong threshold?"* Too high: valid questions get refused (and turn into support
  tickets). Too low: irrelevant chunks reach the model and invite made-up answers.

---

## 8. How do you make the model stick to the sources and cite them?

**Approach used:** strict rules in the system prompt (only the excerpts, cite as [n], an exact fallback
sentence, excerpts are data, not instructions), numbered excerpts with file/page headers, low temperature.
The UI maps [n] to source cards.

**Alternative 1: free answering, with sources only shown "for reference".** Fluent, but there's no link between claims and sources, so you can't check either.

**Alternative 2: structured output** (JSON with `answer` and `citations: [chunk_ids]`). Easier to validate
in code; streaming partial JSON is awkward.

**Cross-questions:**
- *"Can the model cite a source that doesn't support the claim?"* Yes. Prompting reduces this but doesn't
  guarantee it. The fix is **verification**: Phase 2 adds a grading step that checks the answer is supported by the chunks.
- *"Where's the prompt-injection risk?"* Inside uploaded files. Rule 3 plus least privilege (no tools, no
  data beyond the student's scope) limits the damage.

**Real-world example:** in 2023 a New York lawyer was sanctioned after filing a brief citing court cases that
ChatGPT had invented. Citations that aren't **tied to retrieved, verifiable sources** are worse than none,
because they look trustworthy.

---

## 9. How does streaming work, and what changes for error handling?

**Approach used:** Server-Sent Events over `POST /chat/ask`: `sources` → `token`… → `done` | `error`. The browser reads the
stream with `fetch` (EventSource can't POST or send our header). `stream_usage=True` keeps token counts available for cost tracking.

**Alternative 1: WebSockets.** Two-way and good for chat with interruptions or multi-user rooms, but more
infrastructure (sticky connections, reconnect logic) for one-way token streaming.

**Alternative 2: no streaming** (return the full answer). Simplest, but users stare at a spinner for several seconds; time-to-first-token matters more than total time.

**Cross-questions:**
- *"Retries with streaming?"* Only **before the first token**. After that the user has seen partial text, so we end with an error event.
- *"Proxies break streaming. Why?"* Some buffer responses (nginx). We send `X-Accel-Buffering: no` and `Cache-Control: no-cache`.
- *"What if the user closes the tab?"* The generator is cancelled. In production you'd also stop the
  upstream LLM call to stop paying for tokens nobody reads.

---

## 10. Why process uploads in the background, and what if it crashes?

**Approach used:** `202 Accepted` after saving the file; FastAPI `BackgroundTasks` runs the pipeline; a status
field (`uploaded → parsing → … → ready | failed`) is polled by the UI; **Re-process** is idempotent (old vectors
are deleted first); duplicates are rejected by content hash.

**Alternative 1: a job queue** (Celery/RQ/Arq with Redis). Survives restarts, retries jobs, scales workers,
and suits bulk uploads. More infrastructure.

**Alternative 2: synchronous processing** in the request. Simplest, but uploads time out on big files and the UI freezes.

**Cross-questions:**
- *"Server restarts while a file is 'embedding'. What happens?"* BackgroundTasks jobs die with the process. At
  startup I mark any document still "in progress" as failed ("Interrupted by a server restart"), so the
  teacher can re-process it. A durable queue would retry automatically, which is the next step at scale.
- *"Why delete vectors before the DB row?"* So a half-finished delete never leaves searchable chunks that point to a missing file.

---

## 11. How do you keep students from seeing other courses' material?

**Approach used:** the retriever's course filter is computed from the **user's identity** (active/completed
enrollments), never from the question or the LLM; it's applied inside the vector search.

**Alternative 1: a collection per course/tenant.** Strong isolation and easy deletion per tenant. Many
small collections are harder to manage, and cross-course search (admin) needs fan-out.

**Alternative 2: a separate vector DB per tenant.** Strongest isolation (for regulated, multi-company SaaS) and the most expensive to run.

**Cross-questions:**
- *"A dropped student?"* Dropped enrollments lose access. That's a product decision written in code (`scopes.py`), and tested.
- *"Could a prompt widen the filter?"* No. The LLM never sees or chooses the filter.

---

## 12. How do you evaluate a RAG system?

**Approach used:** a labelled **retrieval** eval: 20 questions phrased like students, each with its known
course/module/topic; metrics hit@1/3/k and MRR; plus off-topic questions that must fall below the threshold.

**Why separate retrieval from generation:** if the right chunk isn't retrieved, no prompt can fix the answer.
Measure the first stage on its own, cheaply (no LLM calls).

**Alternative 1: synthetic eval sets** (an LLM generates questions from each chunk). Scales to hundreds of
questions quickly, but questions tend to copy the chunk's wording (too easy) and need human review.

**Alternative 2: online signals** (👍/👎, "not helpful" → ticket rate). Real user behaviour, but it arrives late, is
noisy and biased (few people click). Phase 5 adds these signals.

**Cross-questions:**
- *"Why phrase questions differently from the text?"* To test meaning, not keyword overlap. Real students paraphrase.
- *"How many questions are enough?"* Enough to cover each topic type and failure mode. Start with 20–50, grow it
  with every real failure you find, and never tune on the same questions you report on.
- *"What about answer quality?"* Phase 7: faithfulness and relevance, with LLM-as-judge plus human spot checks.

---

## Rapid-fire

| Question | Answer |
|---|---|
| Chunk overlap, why? | So an idea cut at a boundary still appears whole in one chunk |
| Why not one vector per file? | It averages everything, so it matches nothing well |
| Payload? | Metadata stored with a vector: used for filters and citations |
| Time to first token? | Latency until the first streamed token. The speed users actually feel |
| Why 202 on upload? | The file is accepted; processing continues asynchronously |
| Idempotent re-process? | Running it twice gives the same result (old chunks deleted first) |
| SHA-256 on upload? | Detects identical content regardless of file name |
| hit@k vs MRR? | hit@k: is the right chunk in the top k at all? MRR: how high is it ranked? |
| Why log `no_context` questions? | They are content gaps: material teachers should add (Phase 5) |
| What's in a citation here? | Course code · file name · page (PDF) or section heading |

---

## Mistakes to avoid

1. Saying "RAG removes hallucinations". It **reduces** them; verification and thresholds are still needed.
2. Tuning chunk size by feel. Say "I measured it with the retrieval eval".
3. Forgetting re-embedding costs when changing the embedding model.
4. Filtering by permission **after** retrieval, or letting the LLM decide the filter.
5. Ignoring the ingestion side (parsing, headers, scanned PDFs). That's where most real RAG failures start.
