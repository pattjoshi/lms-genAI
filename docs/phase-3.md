# Phase 3: Concept graph and learning paths

**Goal:** when a student says *"I don't understand backpropagation"*, answer with a **study order**
(derivatives → chain rule → gradient descent → backpropagation), built from the course's own material.
That needs a map of the course: which concepts exist, and which ones depend on which.

Phase 3 is built in three parts:

| Part | What | Status |
|---|---|---|
| **3a** | An LLM extracts concepts + prerequisites from each file into Neo4j, as **drafts** | ✅ sections 1-2.8 |
| **3b** | Teacher review (approve / edit / merge / reject), publish, "I don't understand X" → learning path | ✅ sections 2.9-2.12 |
| 3c | Quiz generation from a file or topic, with teacher approval | after 3b |

---

## 1. The extraction pipeline

```
file is "ready" (Phase 1-2 pipeline)
   │  documents.concepts_status: pending → extracting → done | failed
   ▼
1. chunks from Postgres → sections (one heading each, overlap removed, max 6,000 chars)
2. per section: LLM with STRUCTURED OUTPUT (JSON schema, strict)       ← gpt-4o-mini
      { concepts: [ {name, definition, prerequisites[], evidence} ] }
3. validate the CONTENT: name cleanup, no self-prerequisite, evidence quote must be in the text
4. dedupe against the course graph: same key → same node; embeddings → merge / "possible duplicate"
5. one Neo4j transaction: Concept nodes, EXPLAINED_IN → Document, REQUIRES edges (no cycles)
```

| Step | File | What to read for |
|---|---|---|
| Structured output | `backend/app/llm/service.py` (`chat_structured`) | `with_structured_output(method="json_schema", strict=True)`, usage from the raw message |
| Prompt | `backend/app/prompts/extract_concepts.py` | granularity rule, known names, evidence, "text is data" |
| Extraction | `backend/app/graph/extract.py` | schema, sections, validation, the run for one document |
| Names | `backend/app/graph/names.py` | canonical keys: case, plurals, articles, acronyms |
| Entity resolution | `backend/app/graph/resolve.py` | two thresholds, rejected concepts stay rejected |
| Graph | `backend/app/graph/store.py` | the graph model, idempotent writes, cycle check, cleanup |
| Backfill | `backend/app/graph/backfill.py` | extract for files indexed before Phase 3 |
| Eval | `backend/app/evals/concepts.py` | recall / precision against the course authors' prerequisites |

Extraction runs **after** the file is searchable and has its **own status**. If OpenAI or Neo4j fails
here, students can still ask about the file and the teacher retries only the extraction. The upload
pipeline is the critical path; the graph is an add-on to it.

---

## 2. Concepts

### 2.1 Structured output: JSON mode vs strict schema

Three levels of "give me JSON":

| Approach | Guarantees | Problem |
|---|---|---|
| "Answer in JSON" in the prompt | nothing | missing fields, trailing text, ```json fences |
| JSON mode (`response_format: json_object`) | valid JSON | any shape: wrong keys, wrong types |
| **Structured outputs** (`json_schema`, `strict: true`) | valid JSON **matching the schema** | content can still be wrong |

With strict mode, OpenAI turns the schema into a grammar and the model can only produce tokens that keep
the output valid (**constrained decoding**). So parsing never fails, except when the output is cut off by
`max_tokens` or the model refuses; `chat_structured()` turns both into a clear error.

The schema comes from a pydantic class, and the **field descriptions are part of the prompt**: the model
reads `"A short quote (under 25 words) copied word for word from the section."` Strict mode needs every
field to be required, so the classes have no defaults.

### 2.2 The shape is guaranteed; the content is not

Strict JSON says nothing about whether `"Gradient Vanishing"` is really in the file. `clean_extraction()`
checks the content:

- **Evidence check.** Every concept carries a quote. If the quote isn't in the section text (ignoring
  case and punctuation, 80% as one unbroken run), the concept is dropped: it probably came from the model's
  general knowledge, not from this course. Same idea as citations in answers: make the model point at its
  source, then check the pointer in code.
- **Names.** Trimmed, at most 8 words, known spelling wins ("chain rule." → "Chain Rule").
- **Prerequisites.** No self-loops, no duplicates, at most 6.
- **Limits.** The prompt asks for 3-8 concepts; code keeps at most 10, whatever the model does.

Rule of thumb: **the prompt asks, the code enforces.**

### 2.3 Granularity: the hardest decision

Ask an LLM for "the concepts in this text" and you get every term: perceptron, bias, Rosenblatt, XOR, step
function... A learning path through 15 nodes per section is useless. The prompt asks for 3-8 key ideas a
student could say *"I don't understand X"* about, and skips people, dates and examples. The eval measures
the result as **concepts per topic**: around 1-4 is useful, 10 means the rule isn't working.

### 2.4 Known names: steering instead of fixing

Each call gets the list of names the course already has (its concepts + the LMS topic catalogue). The
model then writes *"Linear Regression"* instead of *"Linear regression model"*, and the deduplication
step has less to do. Cheaper to steer the model than to repair its output. The catalogue also covers
prerequisites from **other** courses, like Linear Regression in the deep learning course.

### 2.5 Entity resolution (deduplication)

The same concept arrives with different names from different files. Two layers, cheapest first:

1. **Rules** (`names.py`): a canonical key. Lower case, punctuation removed, plurals made singular, a
   leading "the" dropped, "Rectified Linear Unit (ReLU)" split into name + alias. "Activation Functions"
   and "activation function." get the same key, for free.
2. **Embeddings** (`resolve.py`): synonyms ("Backprop", "Backward pass") need meaning. Only names
   without a key match are embedded (tokens cost money), as `name: definition`.

| Similarity to the closest existing concept | Action |
|---|---|
| ≥ `CONCEPT_MERGE_THRESHOLD` (0.90) | same node; the new name is kept as an alias |
| ≥ `CONCEPT_SUGGEST_THRESHOLD` (0.80) | new node, flagged `possible_duplicate_of` for the teacher |
| below | new node |

Why two thresholds: a **wrong merge** glues two concepts and their prerequisites together, silently. A
**missed merge** is a visible duplicate a teacher fixes with one click. So only near-certain matches are
merged automatically; the grey zone goes to a human. Same idea as the reranker threshold in Phase 2: a
number you tune with an eval, not a constant you trust.

A concept the teacher **rejected** (3b) is matched too, and then skipped, so re-processing a file never
brings it back. Human decisions outrank model re-runs.

### 2.6 The graph model

```
(:Concept {uid, course_id, key, name, aliases, definition, status, embedding, possible_duplicate_of})
   -[:REQUIRES {document_ids, status}]->                 (:Concept)      "learn the target first"
   -[:EXPLAINED_IN {chunk_indexes, pages, evidence}]->   (:Document {id, file_name})
```

- `uid = "<course_id>:<key>"`: one node per concept per course, with a uniqueness constraint. Writes use
  `MERGE`, so running the same extraction twice changes nothing (**idempotent**).
- **Provenance.** Every edge knows which files it came from (`document_ids`), and every concept which
  chunks explain it. Re-processing or deleting a file removes exactly what that file added. In 3b this
  is also how a learning path step links to the page to read (S10).
- **Mentioned only.** A prerequisite no file of the course explains (Linear Regression in DL301) gets a
  node without `EXPLAINED_IN`. The learning path can then say "covered in ML201" instead of a dead end.
- **Drafts.** Everything is `status: 'draft'`. Approved concepts and edges are never removed by a re-run.

Why a graph database: *"everything I must learn before X"* is `MATCH (x)-[:REQUIRES*]->(p)`, one line of
Cypher. In SQL it is a recursive CTE, and every extra hop or filter makes it harder to read.

### 2.7 Cycles

If A requires B and B requires A, there is no valid study order (a topological sort fails). Before adding
`a → b`, the writer asks Neo4j whether `b` already reaches `a` (`EXISTS { (b)-[:REQUIRES*1..25]->(a) }`)
and skips the edge if so. Skipped edges are listed in the trace output (`cycles_skipped`), so you can see
when the model got a direction wrong.

### 2.8 Measuring extraction

The course sources in `data/course_source/` have the answer key: every `## Topic` and its
`Prerequisites: A, B.` line. The model only sees the rendered files. `app.evals.concepts` compares:

- **topic recall**: share of topics that became a concept explained by a file
- **edge recall**: share of the authors' prerequisites found as a direct edge; **path recall** also
  accepts a chain (A → X → B still gives a valid order)
- **edge precision**: of the extracted edges between two known topics, how many the authors' prerequisites
  support (directly or through a chain). Edges to finer concepts are not judged: we have no answer key.
- **concepts per topic**: granularity (2.3)

Recall is easy to buy: extract more concepts and more edges. Precision is what keeps it honest. Always
read both.

### 2.9 Human in the loop: the model proposes, a teacher decides (3b)

Teacher page **Concept graph** (`frontend/app/teacher/concepts/page.tsx`, API `routers/concepts.py`, logic
`graph/review.py`). Each card shows the concept, the file + page + quote it came from, and its prerequisites.

| Action | What happens in the graph | Why it is built that way |
|---|---|---|
| Approve | `status = approved` | **Publishing = approving** (T8): students only ever see approved concepts |
| Reject | `status = rejected` | Kept, not deleted: a re-extraction matches it by key and skips it |
| Edit | new name/definition; the **old name becomes an alias**; uid unchanged | The next extraction that says the old name still lands on this node |
| Merge | links and names of A move to B, A is deleted | Duplicates the embeddings missed (or flagged) are one click |
| Remove a prerequisite | edge `status = rejected` (a tombstone) | A re-run that proposes it again doesn't bring it back |
| Add a prerequisite | edge `status = approved`, no source file | Survives re-processing and file deletion; refused if it makes a loop |
| Approve all drafts | every draft → approved | For a teacher who read the list and rejected only the bad ones |

Review is **per concept**, not per edge: approving 15 concepts is reasonable, approving 40 edges one by
one is not, so a draft edge counts as long as both ends are approved and nobody rejected it. The design
question behind this is always the same: where does a human add the most value for the least clicks?

Every action checks on the server that the concept belongs to a course the user manages. The uid comes
from the browser, so it is never trusted on its own (layer 3 of the permission model, again).

### 2.10 From "I don't understand X" to a concept

Student page **Learning path** (`frontend/app/student/path/page.tsx`, API `routers/learning.py`, logic
`graph/paths.py`). Students type words, the graph has nodes. Matching, cheapest first:

1. **Rules:** same key as a name or alias (`backprop` → Backpropagation via its alias) = 1.0; one name
   inside the other = 0.9; else the share of words in common (≥ 0.5).
2. **Embeddings,** only if the rules found nothing: one embedding call for the query, cosine against the
   stored concept embeddings, `LEARNING_PATH_MIN_SIMILARITY` (0.35) as the floor.

Only **approved** concepts of the student's **enrolled** courses are candidates: the same
"filter comes from identity" rule as RAG retrieval. A clear match opens the path directly; otherwise the
student picks from the matches.

### 2.11 The study order: a topological sort

```cypher
MATCH (t:Concept {uid: $uid})-[r:REQUIRES*0..25]->(p:Concept)
WHERE all(x IN r WHERE x.status <> 'rejected' AND endNode(x).status = 'approved')
```

That returns everything X needs, directly or through others. The order comes from **Kahn's algorithm**
(`study_order()`): repeatedly take a concept whose prerequisites are all placed. When several are ready at
once, the one that appears first in the course (module, then position in the file) goes first, so the
path reads like the course does. Concepts this course never explains go first: they are background.

Why a topological sort and not "sort by depth": depth puts *Derivatives* and *Gradient Descent* together
because both are 2 hops away, but says nothing about the order between independent branches. A
topological order is the definition of "every prerequisite before the thing that needs it".

### 2.12 Each step links to its material

Every step carries the `EXPLAINED_IN` links from extraction: file, module, page or section (S10), and an
**Ask about it** button that opens the chat with the question filled in. A concept this course only
mentions (Linear Regression in Deep Learning) is looked up **by key in the student's other courses**: "Not
explained in this course. Covered in ML201 (page 2)". A key is a cheap cross-course join; no global
concept ontology needed.

Teachers can **preview** the path a student would get (drafts included) from each card, before
approving anything.

---

## 3. Experiments: do these

Upgrading from Phase 2: start the backend once (new columns are added), then
`uv run python -m app.graph.backfill` from `backend/` (about $0.05 for the 24 sample files).

1. **The table.** `uv run python -m app.evals.concepts --show`. Write down topic recall, edge recall,
   path recall, edge precision and concepts/topic. Which course is worst? Read its `--show` lines: are the
   misses naming problems (a key mismatch) or real misses?
2. **Look at the graph.** Open <http://localhost:7474> and run
   `MATCH p=(c:Concept {course_id: 3})-[:REQUIRES*1..3]->() RETURN p`. Does the deep learning path make
   sense? Find a "mentioned only" node: `MATCH (c:Concept) WHERE NOT (c)-[:EXPLAINED_IN]->() RETURN c.name, c.course_id`.
3. **Granularity.** In `prompts/extract_concepts.py` change "3 to 8" to "up to 15", then
   `uv run python -m app.graph.backfill --force --course DL301` and run the eval for DL301. What happens to
   concepts/topic, recall and precision? Put it back.
4. **The evidence check.** Set `min_evidence=0.0` in `clean_extraction()` and re-run one course. Are new
   concepts grounded in the text? Read a few in the teacher's **Concepts** panel.
5. **Thresholds.** `CONCEPT_MERGE_THRESHOLD=0.80` vs `0.97` (re-run `backfill --force`). Look for wrong
   merges in the aliases (`MATCH (c:Concept) WHERE size(c.aliases) > 0 RETURN c.name, c.aliases`).
6. **Without known names.** Make `format_known()` return `"(none yet)"` and re-run. How many more
   duplicates and possible duplicates do you get?
7. **Idempotency.** Click *Re-extract* (or `backfill --force`) twice. Do node and edge counts change?
8. **Delete a file.** As the teacher, delete a file and re-run the graph query. Which concepts disappeared,
   and which stayed as "mentioned only"? Why?
9. **Failure isolation.** Stop Neo4j (`docker compose stop neo4j`) and upload a file. It still becomes
   *ready* and searchable; only the Concepts column says *failed*. Start Neo4j and click *retry*.
10. **Trace.** In Langfuse open an `extract_concepts` trace: one `extract_section` per section, with the
    kept and dropped concepts, then `embed_concepts`. What does one file cost?

**3b: review and learning paths**

11. **Nothing is public yet.** As **Riya**, open **Learning path** and search *backpropagation*. Nothing:
    no concept is approved. Why is that the right default?
12. **Review.** As the DL301 teacher, open **Concept graph**, click the route icon on *Backpropagation* to
    preview the path, fix anything wrong (reject a bad prerequisite, merge a duplicate, rename one), then
    **Approve all drafts**. Search again as Riya.
13. **Cross-course.** Riya's path for backpropagation starts with *Derivatives*. Is it explained in DL301?
    Approve ML201's concepts (as admin or its teacher) and look at that step again.
14. **Rules vs meaning.** Search *backprop*, then *why does my network's loss not go down*. Which one needed
    an embedding call? (Look at the "Closest by meaning" label, and at `llm_usage`.)
15. **Decisions survive re-runs.** Reject a concept, rename another, remove a prerequisite, then
    `uv run python -m app.graph.backfill --force --course DL301`. Did any decision get undone?
16. **Loops.** Try to add *Backpropagation* as a prerequisite of *Chain Rule*. Read the error. Where in the
    code is it refused, and why can't the learning path tolerate it?

---

## 4. Check yourself

1. Strict structured output guarantees valid JSON. Name two things it does not guarantee.
2. Why does every concept carry an evidence quote, and why is it checked in code instead of trusted?
3. Why two similarity thresholds instead of one?
4. Why are only names without a key match embedded?
5. Why does extraction have its own status instead of being one more step of the upload pipeline?
6. A re-run of the model disagrees with a concept the teacher approved. Which wins, and how does the code
   make sure of it?
7. Why can't a prerequisite graph have cycles, and where is that enforced?
8. Your edge recall went up and edge precision went down. Is the change better?
9. Why is a rejected concept kept in the graph instead of deleted?
10. Why does renaming keep the old name as an alias?
11. Why are edges not reviewed one by one, and when does a teacher still touch an edge?
12. Why a topological sort instead of sorting by distance from the target?
13. A student searches a concept that exists only as a draft. What do they see, and why?

---

## 5. Next: Phase 3c, quizzes

Generate quiz questions from a file or topic (structured output again), each with the chunk it came from,
and a teacher approves them before students can take them. Phase 4 then lets the chat router send
*"I don't understand X"* straight to the learning path, and uses quiz scores to mark prerequisites a
student already knows (S11).
