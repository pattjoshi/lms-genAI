# Interview prep: Phase 2 (better retrieval)

Same format: **approach → why → 2 alternatives → cross-questions → real-world example.**
"How would you improve a RAG system?" is the most common follow-up to "explain your RAG pipeline", and
the strongest answers come with **measured** results. So fill in your own numbers from
`uv run python -m app.evals.retrieval --compare` before an interview.

---

## 0. "How did you improve retrieval?" (60 seconds)

> "First I measured. Phase 1 was plain vector search: hit@5 0.90, MRR 0.84 on 20 questions. Hit@1 and hit@5
> showed two separate problems: right chunk found but ranked low, and right chunk not found at all.
>
> For **finding**, I added hybrid search: every chunk has a dense embedding and a BM25 sparse vector in
> Qdrant, both searched in one request and merged with Reciprocal Rank Fusion. That fixes exact-term
> questions like 'EXPLAIN ANALYZE' or 'dying ReLU'. For follow-ups like 'give me an example', an LLM rewrites
> the question into a standalone one, using the last 3 turns of the chat loaded from the database.
>
> For **ranking**, a local cross-encoder reranks the top 20 candidates, and its score is also the relevance
> gate: if nothing passes, one corrective retry rephrases the query in textbook terms.
>
> Every step is a flag, so the eval runs 5 modes on a 48-question set with categories (keyword, paraphrase,
> follow-up, off-topic) and shows which step fixed which question. If a step fails, like the reranker model
> not loading, retrieval degrades instead of failing."

**Numbers to remember:**

| Fact | Value |
|---|---|
| Phase 1 baseline (20 questions) | hit@1 0.80 · hit@5 0.90 · MRR 0.838 · no-answer 2/2 |
| Phase 2 eval set | 48 questions: 20 semantic, 12 keyword, 6 paraphrase, 5 follow-up, 5 off-topic |
| Modes compared | dense, hybrid, dense+rerank, hybrid+rerank, full |
| Candidates before rerank | 20 per search → best 5 |
| RRF constant | k = 60 |
| Reranker | ms-marco-MiniLM-L-6-v2, ~80 MB, ONNX on CPU, ~0.1–0.3 s for 20 chunks |
| Thresholds | cosine 0.25 (no reranker) · reranker 0.02 (0–1 after sigmoid) |
| Extra cost per question | 0 LLM calls usually; +1 small call for a follow-up or a corrective retry (~$0.00003) |
| Your Phase 2 numbers | *(fill in from --compare)* |

---

## 1. Why hybrid search?

**Approach used:** dense (embedding) search + BM25 keyword search on the same chunks, fused with RRF.

**Why:** embeddings match meaning but blur rare exact tokens: function names, SQL keywords, acronyms,
error names. Students paste exactly those. BM25 is exact on rare tokens but blind to synonyms. Their
failures barely overlap, so combining them raises recall cheaply: BM25 runs inside Qdrant, with no extra
API cost.

**Alternative 1: dense only, with a better or fine-tuned embedding model.**
- ✅ One index, one query; fine-tuning on course Q&A pairs can teach domain terms.
- ❌ Needs training data and re-embedding everything; still weak on unseen identifiers (a new library name).
- **I'd use it** when there's a large labelled set of real questions and keywords rarely matter.

**Alternative 2: learned sparse vectors (SPLADE).**
- ✅ Like BM25 but a model decides term weights and adds related terms ("car" → "vehicle").
- ❌ A model run per chunk and per query, bigger vectors, less transparent than BM25.
- **I'd use it** when BM25 recall is the bottleneck and the latency budget allows.

**Cross-questions:**
- *"How is BM25 stored in a vector DB?"* As a sparse vector: `{hash(word): tf-weight}`. Qdrant applies IDF at
  query time (`Modifier.IDF`), so adding a document never forces re-weighting the old ones.
- *"Why crc32 for word ids, not Python's hash()?"* `hash()` is randomised per process; ids would change on
  restart and silently break keyword search. You need a stable hash.
- *"What about `pd.merge` or `k-means`?"* My tokenizer keeps the compound **and** its parts, so both `pd.merge` and
  `merge` match.
- *"Stemming?"* Snowball: "joins" → "join". It raises recall; it can over-merge ("normalization" → "normal").
  Measured, not assumed.

**Real-world example:** Elasticsearch, OpenSearch, Weaviate, Qdrant and Azure AI Search all ship hybrid
search (Azure fuses with RRF). Microsoft's published Azure AI Search benchmarks found hybrid search plus
semantic reranking beat vector-only search across their customer datasets.

---

## 2. How do you merge two result lists?

**Approach used:** Reciprocal Rank Fusion: `score = Σ 1/(60 + rank)`; scores are ignored, only ranks count.

**Why:** cosine (0–1) and BM25 (0–∞, depends on the query) are on incomparable scales. RRF needs no
normalisation and no tuning, and rewards agreement: rank 2 in both lists beats rank 1 in one.

**Alternative 1: weighted score fusion** (min-max normalise each list, then `α·dense + (1−α)·bm25`).
- ✅ Uses how *confident* each list is, not only the order; α can be tuned.
- ❌ Min-max on 20 results is unstable (one outlier squeezes the rest); α must be re-tuned per dataset.
- **I'd use it** with a labelled set big enough to tune α reliably.

**Alternative 2: let the reranker do the merging** (union of both lists, rerank everything, no fusion).
- ✅ Simplest, and the reranker is the strongest signal anyway.
- ❌ Without the reranker (failure, or turned off for latency) you have no merged order.
- **What I did:** both. RRF orders the candidates, the reranker re-orders them, and RRF remains the
  fallback when the reranker isn't available.

**Cross-questions:**
- *"Why k = 60?"* From the original RRF paper (Cormack et al., 2009). Small k makes the top ranks dominate;
  large k flattens. My eval can test 10 vs 200.
- *"Client-side or server-side fusion?"* Qdrant can fuse server-side (prefetch + `FusionQuery`). I send
  both searches in one `query_batch_points` request and fuse in Python, so I can show each chunk's
  meaning rank and keyword rank in the UI.

**Real-world example:** Elasticsearch ships an `rrf` retriever, and OpenSearch's hybrid search offers both
min-max score normalisation (alternative 1) and RRF. RRF is the usual first choice because it needs no tuning.

---

## 3. Why a reranker, and which one?

**Approach used:** a cross-encoder (`ms-marco-MiniLM-L-6-v2` via fastembed/ONNX), run locally on the 20
candidates; its score orders the final top 5 and decides relevance.

**Why:** the first search uses a bi-encoder: question and chunk are embedded separately, which is fast but
never compares them word by word. A cross-encoder reads both together and is much more precise, but costs
one model run per pair. So the fast search narrows to 20 and the precise model orders those 20. Local means
free, private, and no extra API key; ~80 MB fits easily in 8 GB RAM.

**Alternative 1: LLM as reranker** (ask gpt-4o-mini to score or order the chunks).
- ✅ No model to host; understands nuance; can explain its choice.
- ❌ Adds 0.5–2 s and money to every question; output must be parsed; scores drift between calls.
- **I'd use it** for low-volume, high-value queries, or listwise reranking of very few candidates.

**Alternative 2: hosted rerank API** (Cohere Rerank, Voyage, Jina).
- ✅ Best quality, multilingual, nothing to host.
- ❌ Another vendor, key and bill; chunks leave your infrastructure; network latency.
- **I'd use it** in production when quality matters more than a dependency.

**Cross-questions:**
- *"Why only 20 candidates?"* Reranking cost grows linearly. If the right chunk isn't in the top 20, the
  reranker can't save it; that's recall's job (hybrid search, rewriting). `RAG_CANDIDATES` is measurable.
- *"What's ColBERT?"* Late interaction: token-level vectors pre-computed per chunk, matched at query time.
  Between bi- and cross-encoder in both speed and quality.
- *"What if the model download fails?"* It degrades: RRF order is used, the UI shows a warning, `/health`
  shows `reranker: unavailable`, and loading is retried only every 5 minutes, not on every question.
- *"Is a model trained on web search OK for course notes?"* It's general relevance; my eval shows whether it
  helps on *my* data. If not, I'd try a bigger model (bge-reranker-base) or fine-tune on logged questions.

**Real-world example:** Bing and Google search have used multi-stage ranking for years: a cheap retrieval
stage over billions of documents, then expensive neural rankers over the top few hundred.

---

## 4. How do you handle follow-up questions?

**Approach used:** conversational query rewriting. If the chat has history, an LLM rewrites the follow-up into
a standalone question using the last 3 turns; only the search uses the rewrite. History comes from the
database by `conversation_id` (renewed by **New chat**), never from the client.

**Why:** "Can you give an example?" has no searchable content. The rewrite resolves "it/that" into the topic.
With no history there's no call, so most questions cost nothing extra.

**Alternative 1: search with the raw history** (concatenate the last turns with the question).
- ✅ No LLM call.
- ❌ Old topics pollute the search; when the student changes topic, the previous one keeps winning.
- **I'd use it** as a cheap fallback when the LLM is unavailable.

**Alternative 2: an agent with memory decides what to search** (tool calling).
- ✅ Handles complex multi-step questions.
- ❌ Slower, costlier, harder to test. That's Phase 4.

**Cross-questions:**
- *"What if the rewrite changes the meaning?"* The prompt says "keep the meaning, don't answer, return it
  unchanged if standalone". The UI shows "Understood as …" so the student can see it, and the eval's
  follow-up category measures it.
- *"Prompt injection through history?"* History is the student's own saved questions, loaded server-side by
  user id; the prompt marks it as data, not instructions. The worst case is a bad search query for the
  student's own question, and the security filter still comes from identity.
- *"Why not rewrite every question?"* Cost and risk: an unnecessary rewrite can only change a good query.

**Real-world example:** LangChain's `create_history_aware_retriever` and LlamaIndex's "condense question"
chat engine implement exactly this, and ChatGPT's search mode visibly rewrites your question before searching.

---

## 5. What if nothing relevant is found?

**Approach used:** a corrective retry (CRAG-style). The reranker grades every chunk; if none passes, one LLM
call rephrases the question in textbook terms, and we search once more. A result is used only if it passes
the same gate. Otherwise: "I couldn't find this", with no answer LLM call.

**Why:** students describe concepts without their names ("my model remembers the training data"). One
cheap rewrite recovers many of these. **Once** keeps cost and latency bounded.

**Alternative 1: HyDE** (generate a hypothetical answer, embed and search with that).
- ✅ The fake answer uses textbook vocabulary, so it often lands near the real chunk.
- ❌ More tokens; the hypothetical answer may contain wrong "facts" that pull in wrong chunks.
- **I'd use it** for very short or vague questions in a domain with consistent vocabulary.

**Alternative 2: multi-query / RAG-Fusion** (generate 3–5 variants, search all, fuse with RRF).
- ✅ Higher recall on every question.
- ❌ Several embeddings plus an LLM call on *every* question, not only failing ones.
- **I'd use it** when recall matters more than cost, e.g. legal research.

**Cross-questions:**
- *"Why not retry until something is found?"* Then everything eventually "finds" something, and off-topic
  questions get confident wrong answers. The gate plus one retry is the guardrail.
- *"How is this different from Self-RAG?"* Self-RAG trains the model to emit reflection tokens deciding when
  to retrieve and whether passages support the answer. I get a similar decision from a reranker threshold,
  with no model training.

**Real-world example:** "deep" or "pro" search modes in answer engines like Perplexity show several search
steps with refined queries when the first results aren't enough: the same retry idea, with more rounds.

---

## 6. How do you choose the relevance threshold?

**Approach used:** with the reranker, `rerank_score ≥ 0.02` (0–1 after sigmoid). Without it, Phase 1's
cosine ≥ 0.25; a chunk found only by keywords counts only if the question as a whole is on-topic (the best
cosine passes). The eval prints a **threshold check**: the lowest score of a correct chunk vs the highest
score among off-topic questions.

**Why:** a threshold should come from data. A gap between the two groups means a safe threshold exists;
overlap means some questions will be wrong either way, and the eval shows which.

**Alternative 1: no threshold, always answer from the top k.**
- ✅ Never refuses.
- ❌ Off-topic questions get answers built from unrelated chunks: hallucination with citations.

**Alternative 2: an LLM grader** ("does this chunk answer the question? yes/no").
- ✅ Understands nuance; no calibration.
- ❌ An LLM call per chunk or per question; slower and costlier than a cross-encoder.

**Cross-questions:**
- *"Why does the reranker need a different threshold than cosine?"* Different model, different scale. Cosine
  values of a given embedding model cluster in a narrow band; reranker logits are spread wide.
- *"How do you stop keyword hits sneaking in for off-topic questions?"* Keyword-only chunks have no cosine,
  so they inherit the question-level check: if the best meaning match is below threshold, they're not used.

**Real-world example:** support bots (Intercom Fin, Zendesk AI) hand off to a human when retrieval confidence
is low instead of guessing. That's the same idea as our `no_context` status, which Phase 5 turns into tickets.

---

## 7. How do metadata filters work, and can the LLM set them?

**Approach used:** "Search in course / module" from the UI becomes a Qdrant payload filter **inside** the
search (pre-filtering), intersected with the courses the user may read. A module of a non-enrolled course
returns nothing.

**Alternative 1: post-filtering** (search, then drop disallowed results).
- ❌ Top 20 may all be filtered away, leaving nothing, and it's a security risk if someone forgets the
  filter step.

**Alternative 2: self-query retriever** (the LLM extracts filters from "in module 2, what is …").
- ✅ Natural for users.
- ❌ The LLM may invent or omit filters. Acceptable for convenience filters, **never** for permission filters.
- **I'd use it** for filters like "only PDFs from 2024", always intersected with the identity filter.

**Cross-question:** *"Do filters slow vector search?"* With payload indexes, Qdrant applies the filter
during HNSW traversal (filterable HNSW); very selective filters switch to a plain scan of the matching
points. That's why `course_id`/`module_id` are indexed.

**Real-world example:** e-commerce search: filtering by brand or price runs inside the search engine, never
after it.

---

## 8. You changed the index format. How do you migrate?

**Approach used:** the app detects the old format and reports it (startup log, `reindex_needed` error) instead
of failing obscurely or deleting data. A `reindex` command drops, recreates and re-processes every current
document (~$0.001). It's idempotent: run it again and it says "nothing to do".

**Alternative 1: blue/green with a collection alias.** Build `course_chunks_v2` alongside, point the alias
`course_chunks` at it when complete. Zero downtime, instant rollback. **The production answer.**

**Alternative 2: in-place migration.** Read each point's existing dense vector, compute BM25 locally, write
both back. No re-embedding cost; more code, and it relies on the old payload being complete.

**Cross-question:** *"How do you avoid paying for re-embedding?"* Store embeddings (or the model version) with
the chunk so a format change can reuse them; re-embed only when the *model* changes.

**Real-world example:** Elasticsearch's reindex API plus index aliases is the standard zero-downtime
pattern; vector DBs copied it.

---

## 9. How do you prove the changes helped?

**Approach used:** an ablation. 5 modes on the same 48 questions and the same index; each mode adds one step.
Per-category hit@5 shows *where* a step helps; a per-question rank table shows *which* questions it fixed or
broke.

**Why:** an average can hide a regression, and a bigger eval set reduces noise: with 20 questions, one
question is 5 points.

**Alternative 1: online A/B test** (half the students get each pipeline; compare thumbs-up rate).
- ✅ Measures real outcomes.
- ❌ Needs traffic and a feedback signal (Phase 5's 👍/👎). Slow.

**Alternative 2: LLM-judged answer quality** (faithfulness, relevance), e.g. RAGAS.
- ✅ Measures the final answer, not only retrieval.
- ❌ Judge bias and cost; that's Phase 7.

**Cross-questions:**
- *"Aren't you overfitting the eval set?"* Risk is real: I wrote the questions knowing the notes. Mitigations:
  questions phrased like students, keep a held-out set, and add real logged questions (Phase 5 content gaps).
- *"What if a step helps on average but breaks one question?"* Read that question's chunks in the details panel.
  Usually it's a threshold or tagging issue, not the step itself.

**Real-world example:** search teams (and recommender teams at Netflix, Spotify) never ship a ranking change
without an offline eval, then an online A/B test.

---

## 10. What does it cost in latency and money?

| Step | Typical latency | Money |
|---|---|---|
| Embed question | 50–200 ms | ~$0.0000002 |
| Qdrant dense + sparse (one request) | 5–20 ms | free |
| Rerank 20 chunks (CPU) | 100–300 ms | free |
| Follow-up rewrite (only with history) | 300–800 ms | ~$0.00003 |
| Corrective retry (only when nothing relevant) | 0.5–1 s | ~$0.00003 + embed |

**Cross-question:** *"Where would you cut first if it's too slow?"* Fewer candidates (20 → 10), a smaller
reranker, or rerank only when the top fused results disagree. Measure with `avg ms` in `--compare`.

---

## 11. What if a step fails?

Each quality step **degrades**, never breaks answers:

- Reranker can't load → RRF order, warning in the details panel, `/health` → `reranker: unavailable`.
- Rewrite LLM call fails → search with the original question, warning shown.
- Old index format → a clear `reindex_needed` message with the exact command.

**Cross-question:** *"Isn't silent degradation dangerous?"* It's not silent: it's in the UI, `/health`, logs and
traces. Silent would be no warning; broken would be no answer.

---

## Rapid-fire

| Question | Answer |
|---|---|
| Dense vs sparse vector? | Dense: every dimension used (meaning). Sparse: one slot per word, mostly zeros (keywords) |
| What does IDF do? | Rare words weigh more; "the" says nothing, "ReLU" says a lot |
| BM25 k1 and b? | k1: how fast repeated words saturate; b: how much long documents are penalised |
| Bi-encoder vs cross-encoder? | Separate embeddings (fast, pre-computable) vs joint scoring (accurate, per pair) |
| Why RRF over score averaging? | Scales differ; ranks are comparable, scores aren't |
| Recall vs precision step? | Hybrid search and rewriting raise recall; reranking raises precision |
| Pre-filtering? | Filter inside the vector search, so top-k is always from allowed data |
| Query rewriting risk? | Changing the meaning; show "Understood as …" and measure it |
| Why sigmoid the reranker logit? | A 0–1 score is easier to read, log and put a threshold on |
| Collection alias? | A stable name pointing at a real collection; swap it for zero-downtime re-index |

---

## Mistakes to avoid

1. "We added a reranker and it got better" without numbers. Say *which* metric moved, on *which* category.
2. Comparing new numbers on a new eval set with old numbers on the old set.
3. Letting the LLM decide permission filters (self-query) instead of intersecting with identity.
4. Reranking hundreds of chunks per question and then blaming the model for latency.
5. Rewriting every question, or retrying in a loop: cost goes up and off-topic questions start "succeeding".
6. Forgetting the old index: a format change without a migration plan breaks search silently.
