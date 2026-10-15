# Phase 4: Routing, an agent, and MCP

**Goal:** one chat box that sends each message to the right part of the LMS. *"How does backprop work?"*
is a course question (RAG). *"I don't understand backprop"* is a learning path. *"Quiz me on joins"* is
practice. *"What are my weak topics?"* is progress. *"My payment failed"* is support. The student should
not have to know which page to open.

Phase 4 is built in two parts:

| Part | What | Status |
|---|---|---|
| **4a** | Intent routing (rules → embeddings → LLM), a LangGraph agent, long-term memory of weak topics, practice questions, support answers from the student's own records, answer confidence | ✅ sections 1-2.9 |
| **4b** | Our LMS as an **MCP server** (tools, resources, prompts, personal access tokens); our agent as an MCP **client** | next |

---

## 1. The chat, now an agent

```
student message
   │
   ▼
memory ── weak topics: quiz averages + what the student said and practised (Postgres)
   │
   ▼
route ─── 1. rules (regex)            free, instant, high precision
   │      2. nearest example vectors  one embedding call
   │      3. LLM classifier           one small structured-output call
   │      (anything unsure → "doubt", the Phase 2 RAG answer)
   ▼
┌──────────┬───────────────┬──────────┬──────────┬─────────┐
│ doubt    │ learning_path │ practice │ progress │ support │
│ RAG      │ concept graph │ quiz     │ memory   │ own     │
│ answer   │ study order   │ checks   │ facts    │ records │
└──────────┴──────┬────────┴──────────┴──────────┴─────────┘
                  │ no concept matches → falls back to doubt
                  ▼
                 END
```

| Step | File | What to read for |
|---|---|---|
| Intents and rules | `backend/app/agent/intents.py` | the 5 intents, examples per intent, tight regex rules, topic extraction |
| Router | `backend/app/agent/router.py` | cheapest first; similarity + margin; LLM fallback; "doubt" on any error |
| Graph | `backend/app/agent/graph.py` | `StateGraph`, conditional edges, `get_stream_writer()` for SSE events |
| Memory | `backend/app/agent/memory.py` | quiz averages + `learner_topics`, when a topic stops being weak |
| Practice | `backend/app/agent/practice.py` | finding passages for a topic, reusing the quiz checks, server-side grading |
| Support | `backend/app/agent/support.py` | template answers from the student's own logins and payments, no LLM |
| Shared path code | `backend/app/graph/study.py` | one learning-path service for the page, the agent and (4b) MCP |
| Streaming | `backend/app/routers/chat.py` | `agent.astream(stream_mode=["custom", "values"])` → SSE |
| UI | `frontend/components/ChatCards.tsx` | route line, path / practice / progress cards |

---

## 2. Concepts

### 2.1 Intent routing: cheapest first

Three ways to decide what a message is about:

| Method | Cost | Good at | Bad at |
|---|---|---|---|
| **Rules** (regex) | free, < 1 ms | clear phrasings: *"quiz me on X"*, *"forgot my password"* | anything phrased differently |
| **Embeddings** (nearest example) | 1 embedding call | paraphrases close to an example | short or mixed messages; needs a margin |
| **LLM classifier** | 1 chat call (~$0.00005) | odd phrasings, context | slowest, can be wrong confidently |

We try them in that order and stop at the first confident answer. Most messages never reach the LLM.
The route is saved on the doubt (`doubts.intent`, `doubts.route`) and shown above each answer
("Learning path · matched a rule · topic *backprop*"), so you can see every decision.

**Rules must be tight.** A rule that fires on a course question is worse than no rule: the student gets a
payment answer to an SQL question. So *"transaction"* alone is not support (SQL has transactions), only
*"my payment…"*, *"money was deducted"*. `test_course_questions_are_not_caught_by_rules` keeps it that way.

### 2.2 Embedding routing: similarity AND margin

Each intent has a handful of example messages, embedded once and cached. A message goes to the intent of
its most similar example only if:

- the best similarity is at least `ROUTE_MIN_SIMILARITY` (0.45): it looks like *something* we know, and
- it beats the best example of any *other* intent by `ROUTE_MIN_MARGIN` (0.04): it is not a tie.

A tie means "ambiguous", and ambiguous goes to the LLM. Without the margin, a message halfway between
"practice" and "doubt" is decided by noise.

### 2.3 The default is the safe intent

When everything fails (no rule, no clear example, the LLM errors), the message is a **doubt**. A RAG
answer to a support question is a bit useless; a support answer to a course question is wrong. Pick the
default whose mistakes cost least.

A learning path needs a **topic**. If the rule matched but the topic is not a concept in the graph
(*"I don't understand why my loop never ends"*), the path node hands over to the doubt node and the route
line says so. Falling back is an edge in the graph, not a try/except.

### 2.4 Why LangGraph

Phase 1-3 chat was one function. With five branches, a fallback and streaming from inside each branch,
a function becomes nested `if`s. LangGraph gives:

- **State**: one `ChatState` dict that every node reads and adds to.
- **Nodes**: plain async functions (`route_node`, `practice_node`, …), easy to test alone.
- **Conditional edges**: `pick_branch` returns the intent, `after_path` returns `doubt` or `END`.
- **Streaming from nodes**: `get_stream_writer()` lets any node send `route`, `card`, `token` events while
  it runs; `astream(stream_mode=["custom", "values"])` gives the router both those events and the final state.

There is no "agent loop" (the LLM picking tools again and again) here on purpose: our branches are known,
so a fixed graph is cheaper, faster and easier to debug. A tool-calling loop arrives with MCP in 4b.

### 2.5 Memory: short-term vs long-term

| | What | Where |
|---|---|---|
| **Short-term** | the last turns of this conversation, for follow-ups | `doubts` rows of the conversation (only course-question turns) |
| **Long-term** | what the student is weak at, across sessions | quiz averages + `learner_topics` (`asked_path`, `practice_wrong`, `practice_right`) |

Long-term memory is stored as **facts**, not as a chat summary written by an LLM. A topic is weak if its
quiz average is below `WEAK_TOPIC_SCORE` (65), or the student asked for its learning path or got practice
answers wrong, until they get as many practice answers right as wrong. Facts can be shown ("quiz average
31%; you said you don't understand it (6×)"), tested (`merge_weak` is a pure function) and corrected.

Weak topics are used in three places: the **progress** answer, **"quiz me"** with no topic (picks the
weakest), and the RAG system prompt (S12: "the student has found these topics hard before; if your answer
relies on one, explain that part simply"; see `RAG_MEMORY`).

### 2.6 Known prerequisites (S11)

The learning path now marks a step **known** when the student's quiz average for that concept is at least
`KNOWN_TOPIC_SCORE` (80). The step stays in the list (dimmed, "you know this · quiz 83%"), so the order
still makes sense; the target is never marked known. This is the same `study.build_path` for the page and
the chat.

### 2.7 Practice questions (S13, S14)

*"Quiz me on X"* finds passages about X in the student's courses (a catalogue topic first, then chunk
headings and tags), and writes `PRACTICE_QUESTIONS` (3) questions with the **same** generator and checks as
teacher quizzes (Phase 3c: quote in the passage, 4 distinct options, shuffled in code).

The difference: nobody reviews them. That is acceptable only because they are labelled practice, never
count as a score, and every answer shows its source so the student can check. The right answers stay on
the server; each answer is graded by `POST /practice/{id}/answers` and written to memory. Answering the
same question twice returns the first result and is not counted twice.

### 2.8 Support without an LLM (S18)

*"I can't log in"* and *"my payment failed"* are answered from the student's **own** `login_events` and
`payments` (every query filtered by `user.id`), with templates. No LLM: it can't invent a refund policy or
promise something support won't do, and it costs nothing. The message is saved with intent `support`;
Phase 5 turns those into tickets.

### 2.9 Confidence (S7)

Each RAG answer gets **high / medium / low** confidence from how far the best source cleared the
relevance threshold (Phase 2). A best score just above the threshold means the material is only loosely
related, so the answer shows a "Not sure" warning and suggests checking the source. This is a cheap
retrieval signal; grading the answer itself (faithfulness) is Phase 7.

---

## 3. Experiments: do these

Start the backend once (the new tables and columns are added), then as **Riya** open **Ask a doubt** with
**Show details** on.

1. **Every route.** Ask *"I don't understand backprop"*, *"Quiz me on backpropagation"*, *"What are my weak
   topics?"*, *"I forgot my password"*, *"How does dropout work?"*. Read the route line on each. Which
   ones needed an embedding or LLM call? Check `llm_usage` (`feature` = `route_embed` / `route_intent`).
2. **Paraphrase.** Ask *"drill me hard on this stuff"* and *"walk me through what comes before attention"*.
   No rule matches: which method decided, and was it right? Hover the route line for the scores.
3. **Margin.** Set `ROUTE_MIN_MARGIN=0` and `ROUTE_MIN_SIMILARITY=0` in `.env`, restart, and repeat 2.
   Do you get more wrong routes? Put them back.
4. **A loose rule.** Add `"transaction"` as a support rule in `intents.py` and ask *"What is a transaction in
   SQL?"*. Then run `uv run pytest tests/test_agent.py`. Put it back.
5. **Fallback.** Ask *"I don't understand why my loop never ends"*. Why did it end up as a course question?
6. **Memory.** Ask *"Quiz me on chain rule"* and get them all wrong, then ask *"What are my weak topics?"*.
   Ask again and get them right: when does it drop off the list?
7. **Known steps.** As Riya, open **Learning path** for *backpropagation*. Which steps are marked known, and
   which quiz scores did that come from? Change `KNOWN_TOPIC_SCORE` to 60 and look again.
8. **Weak topics in the prompt.** In Langfuse, open a `rag_answer` trace: find the weak-topics line in the
   system message. Ask a DB201 question as **Arjun**: which weak topics does that prompt carry?
9. **Support is scoped.** As **Karan**, ask *"I can't log in"*. As Riya, ask the same. Where in
   `support.py` is the other student's data kept out?
10. **Confidence.** Ask something your courses barely cover (*"What is a transformer decoder?"* as Riya).
    What confidence do you get, and what does the warning say?

---

## 4. Check yourself

1. Why route with rules first, then embeddings, then an LLM, instead of always asking the LLM?
2. What does the margin check protect against that the similarity threshold does not?
3. Why is "doubt" the default intent, and not "support"?
4. *"Quiz me on my weak topics"* mentions weak topics but is a practice request. How does the progress
   rule avoid catching it?
5. Why is the learning-path fallback an edge in the graph instead of an exception handler?
6. Why a fixed LangGraph graph instead of an LLM agent that picks tools in a loop? When would you switch?
7. Why store long-term memory as facts (scores, counts) instead of an LLM-written summary of the student?
8. When does a weak topic stop being weak? What would go wrong if one right answer cleared it?
9. Practice questions are not reviewed by a teacher. What makes that acceptable, and what would not be?
10. Why are support answers templates with no LLM?
11. Why is confidence computed from retrieval scores, and what can it not tell you about the answer?
12. Where do the agent's decisions show up for debugging (UI, database, traces)?

---

## 5. Next: Phase 4b (MCP)

Every capability above (search, ask a doubt, learning path, weak topics, practice) becomes a tool on our own
**MCP server** at `/mcp`, with personal access tokens mapped to the same permissions. MCP Inspector and
Claude Desktop can then call them, and our agent calls the same tools as an MCP client.
