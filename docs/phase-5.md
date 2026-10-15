# Phase 5: Tickets and the feedback loop

**Goal:** when the AI can't help, a person does, and the AI learns from that person. A question the course
material can't answer, an answer the AI isn't sure about, a 👎 from a student, and every login or payment
problem become a **ticket**. Support sees everything the AI saw and said, fixes the answer, and resolves.
A resolved course answer goes into a **knowledge base**, and the next student who asks the same thing gets
that verified answer from the AI. Teachers see what students ask most, grouped by meaning, and which
questions their material doesn't cover.

**Done when:** a resolved ticket's answer is used by the AI the next time. Try it in experiment 1.

---

## 1. The loop

```
student asks ──► agent (Phase 4) ──► answer streamed
                                        │
          no answer · low confidence · login/payment · later a 👎
                                        ▼
                                  ticket (open)
                                        │  support: full context, similar tickets,
                                        │  the student (only while open), edits the AI draft
                                        ▼
                                  resolved ──► the student sees it in My tickets
                                        │
                          course question + "save to knowledge base"
                                        ▼
                              faq_entries (question vector + answer)
                                        │
next student asks the same ──► retrieval step 7 finds it ──► "Support answer (verified)" is source [1]
```

| Step | File | What to read for |
|---|---|---|
| Tables | `backend/app/models.py` | `Ticket`, `FaqEntry`, and the new `doubts` columns (`confidence`, `feedback`, `question_vec`) |
| Tickets | `backend/app/tickets/service.py` | when a message becomes a ticket, the context package, P8 scope, resolve and the knowledge base |
| Knowledge base | `backend/app/tickets/faq.py` | an FAQ entry as a retrieval source; the threshold |
| Retrieval | `backend/app/rag/retriever.py` | step 7: the FAQ search reuses the query vector |
| Vectors | `backend/app/tickets/vectors.py` | cosine, nearest, greedy grouping (and why not a vector DB here) |
| Insights | `backend/app/tickets/insights.py` | most asked doubts and content gaps for teachers |
| Chat | `backend/app/routers/chat.py` | auto tickets before `done`; `POST /chat/doubts/{id}/feedback` |
| API | `backend/app/routers/tickets.py` | queue, detail, claim, resolve, knowledge base, insights |
| MCP | `backend/app/mcp_server/server.py` | `my_tickets`, and `create_ticket`: a write tool that asks first |
| Old messages | `backend/app/tickets/backfill.py` | tickets for unanswered questions saved before Phase 5 |
| UI | `frontend/components/TicketQueue.tsx`, `app/student/tickets`, `app/support/kb`, `app/teacher/insights` | the pages |

---

## 2. Concepts

### 2.1 Human in the loop: where to put the human

A person can't read every answer, so the system must decide **which** answers need one. We use signals we
already have, cheapest first:

| Signal | Reason | Why it is a good trigger |
|---|---|---|
| Nothing relevant was retrieved | `no_answer` | the AI said so honestly; a person can still answer |
| Relevant, but only just (Phase 4 confidence = low) | `low_confidence` | the answer might be wrong; a person checks |
| The student pressed 👎 | `thumbs_down` | the only signal that comes from the reader |
| Login or payment message | `support` | about one person's account; the template answer is a first reply, not the end |
| The student asked support directly | `student` | anything else |

What we **don't** do: ask an LLM "is this answer good?" on every message. That doubles the cost and is
itself unreliable (Phase 7 measures LLM judges properly). The triggers above are free.

The cost of the triggers is volume: every off-topic question ("who won the cricket world cup?") is a
`no_answer` ticket. `TICKET_ON_NO_ANSWER=false` turns that trigger off; Phase 7's off-topic guardrail
removes most of them properly.

### 2.2 One ticket per message

`tickets.doubt_id` is unique. A 👎 on a message that already has a ticket (say low confidence) marks that
ticket `thumbs_down` instead of opening a second one, and a 👎 on an answer support already resolved puts
the ticket back in the queue. Duplicates waste the scarcest resource here: support's time.

### 2.3 Context packaging (P3)

The worst support experience is asking the student to repeat themselves. The ticket detail packages:

- the question, and the **query that was actually searched** (after the Phase 2 rewrite)
- every retrieved passage, with its score and whether it was used, read back from Postgres by
  `document_id` + `chunk_index` (the doubt row stores the source list without the text)
- the AI's answer (the **draft** support starts from), its confidence, the route that was taken
- the 👎 comment, if any
- the student: enrollments, and only for the kind of ticket: payments for a payment problem, logins for a
  login problem

This is the same idea as a good bug report: everything needed to act, nothing to go and look up.

### 2.4 Data scope: the ticket is the key (P8)

Support's row in the permission matrix has said `TICKET_STUDENT` since Phase 0. Phase 5 makes it real:
support sees a student's records **only through a ticket, and only while it is open**
(`service.can_see_records`). Once resolved, the detail shows the conversation and the student's name, but
not their payments or logins. Admins see everything. Support can't list students at all.

This is access by **purpose**: the reason to see a record (helping with this problem) has an end.

### 2.5 The knowledge base: a feedback loop without fine-tuning

"The AI learns from support" sounds like training. It isn't: the model never changes. We add the verified
answer to what **retrieval** can find:

1. On resolve with "save to knowledge base", the question's vector, the question and the answer go into
   `faq_entries`, tied to the ticket's course.
2. Retrieval step 7 compares the student's question (the vector step 2 already computed, so no extra
   embedding call) with the active entries of the courses the student may read.
3. An entry with cosine ≥ `FAQ_MIN_SIMILARITY` (0.80) becomes source [1], labelled
   *Support answer (verified)*, in front of the course passages. The RAG prompt has one more rule: prefer it.
4. Confidence for that answer is **high**: a person wrote it for this question.

Why this beats fine-tuning here: it works the moment support clicks Resolve, it is scoped by course like
the material, it can be withdrawn (the knowledge base page), and you can see which source the answer came
from. Fine-tuning would take hours, can't be undone per answer, and can't be scoped per student.

**Why 0.80, higher than the 0.25 material threshold?** A course passage is general; a support answer was
written for **one** question. *"What is dropout?"* and *"Why does dropout reduce overfitting?"* are close
in meaning, but the first answer is wrong for the second. Only near-paraphrases should reuse it.

**What never goes in (P6):** login and payment answers are about one person's account, so the server
refuses them. For course questions the box is ticked by default, and support unticks it for a private or
one-off answer ("your deadline is extended to Friday").

### 2.6 Where the vectors live, and why not Qdrant

The plan said "a FAQ collection" in Qdrant. We keep these vectors in **Postgres JSON columns** and compare
them in Python (`vectors.py`) instead:

- The numbers are small: a few hundred knowledge-base entries, a few thousand questions. A Python loop over
  1,000 vectors of 1,536 numbers takes a few milliseconds.
- Everything about a ticket stays in one transaction: resolving a ticket and adding its FAQ entry either
  both happen or neither does. With a second store you need to handle "saved in Postgres, failed in Qdrant".
- Filtering (active, course) is plain SQL.

At ~50k+ vectors, or many searches a second, move them into a real index: a second Qdrant collection, or
**pgvector** inside Postgres (an `ivfflat`/`hnsw` index, still one transaction). Knowing when a vector DB is
**not** needed is part of knowing vector DBs.

### 2.7 Similar past tickets (P7)

The same embedding answers "has someone asked this before?". Resolved tickets of the same category with
cosine ≥ `SIMILAR_TICKET_MIN` (0.75, lower than the FAQ threshold: here a person reads the result) are shown
with their answer and a **Use this answer** button. A ticket's vector is computed when support first opens
it, not when it is created: chatting never waits for it, and a ticket nobody opens costs nothing.

### 2.8 Grouping questions by meaning (T13, T14)

Counting exact strings misses that *"how do I stop overfitting?"* and *"my model memorises the training
set"* are one question. So each question is embedded once (kept on `doubts.question_vec`) and grouped:

**Greedy leader clustering** (`vectors.group`): go through the questions; each joins the group whose centre
it is most similar to, if that is at least `INSIGHTS_GROUP_SIMILARITY` (0.80), otherwise it starts a new
group. The centre is the running **sum** of the member vectors (cosine ignores length, so the sum points
the same way as the mean). The label is the member closest to the centre: the most typical wording.

| Method | Number of groups | Good | Bad |
|---|---|---|---|
| **Leader (ours)** | follows from the threshold | one pass, no k, the threshold means "same question" | order matters a little |
| k-means | you choose k | well known | what is k for a month of questions? every point forced into a group |
| HDBSCAN | found from density | finds odd shapes, marks noise | a library and parameters to explain |
| LLM labelling | any | nice names | cost per run, not repeatable |

**Content gaps** are the same grouping over the questions that were not answered, had low confidence or got
a 👎. A big gap group is a page the teacher should add. Each group also shows the furthest ticket state, so
a gap support already answered into the knowledge base says so.

Teachers see questions and counts, never who asked. Questions a student hid from their history still count.

### 2.9 A write tool that asks first

`create_ticket` is the first MCP tool that sends something to a person. Called without `confirm`, it only
returns a preview and says "show this to the user, call again with confirm=true if they agree". MCP has no
built-in "are you sure?", so the confirmation is part of the tool's contract. Its annotations say
`readOnlyHint=false`, and only students may call it. The chat's own assistant does **not** get this tool
(`LMS_TOOLS` in `assistant.py`): in a single chat turn it couldn't ask the student before confirming.

---

## 3. Experiments: do these

Start the backend once (it adds the new tables and columns). Optionally run
`uv run python -m app.tickets.backfill` to turn your earlier unanswered questions into tickets.

1. **The loop.** As **Riya**, ask something DL301 doesn't cover, like *"What is gradient clipping?"*. Note
   the line under the answer and the ticket number. As **Rohan Das** (support), open **Ticket queue**, open
   the ticket, write an answer, keep **Save to knowledge base** ticked (course DL301) and **Resolve**. As
   Riya, open **My tickets**, then ask *"what's gradient clipping"* in a new chat. Which source is [1], and
   what confidence does the answer have?
2. **Scope of the knowledge base.** Ask the same as **Arjun Mehta** (not enrolled in DL301). Does he get the
   verified answer? Why not?
3. **Threshold.** Ask a near question (*"Why does gradient clipping help RNNs?"*). Was the verified answer
   used? Set `FAQ_MIN_SIMILARITY=0.6`, restart, ask again. Is the answer still right for the question?
4. **👎.** Ask a question that gets a good answer and press 👎 with nothing else. Find the ticket: what is its
   reason and draft? Press 👎 on an answer that already has a ticket: how many tickets now?
5. **Context.** In a low-confidence ticket, open **Passages the AI read**. Was the AI's draft supported by
   them? Would you have answered differently?
6. **P8.** As Riya, ask *"my payment failed but money was deducted"*. As Rohan, open the ticket: what do you
   see about Riya? Resolve it, open it again: what disappeared? Open it as **Neha Kapoor** (admin,
   **Tickets**).
7. **No knowledge base for accounts.** Try to tick **Save to knowledge base** on the payment ticket. Then try
   `POST /tickets/{id}/resolve` with `"save_to_kb": true` in `/docs`. Which layer refuses?
8. **Similar tickets.** Resolve one ticket, then ask a paraphrase of it as another student. Open the new
   ticket: is the old one listed under **Similar resolved tickets**? Click **Use this answer**.
9. **Insights.** As **Suresh Rao**, open **Doubt insights**. Ask three paraphrases of one question as
   different students first. Are they one group? Set `INSIGHTS_GROUP_SIMILARITY=0.95`, restart, reload.
10. **Cost.** Look at `llm_usage` for `ticket_embed` and `insights_embed`. When were they called, and why
    does reloading the insights page not call the embedding again?
11. **MCP.** In MCP Inspector (as Riya), call `create_ticket` without `confirm`, then with `confirm: true`,
    then `my_tickets`. Call `create_ticket` with a teacher's token.
12. **Withdraw.** On **Knowledge base**, withdraw the gradient clipping entry and ask again as Riya.

---

## 4. Check yourself

1. Which signals open a ticket, and why not ask an LLM to grade every answer instead?
2. Why does a 👎 on a message that already has a ticket not open a second one?
3. What does support see for a ticket, and why the searched query and not only the question?
4. What exactly can support see about a student, and when does it stop? Where is that rule in code?
5. "The AI learns from support." What changes, and what doesn't? Why not fine-tune?
6. Why is the knowledge-base threshold (0.80) so much higher than the material threshold (0.25)?
7. Why are login and payment answers never saved to the knowledge base?
8. Why keep these vectors in Postgres instead of Qdrant? When would you move them, and to what?
9. How does leader clustering work, and why is comparing with the sum of vectors the same as the mean?
10. Why not k-means for "most asked doubts"?
11. Why is a ticket's vector computed when support opens it, not when it is created?
12. Why does `create_ticket` need `confirm`, and why doesn't the chat's assistant get it?
13. A wrong answer is saved to the knowledge base. What limits the damage, and how is it undone?

---

## 5. Next: Phase 6

Phase 6 is the SQL agent: every role asks about its own data in plain English (*"which of my students
failed the last quiz?"*), and the answer is SQL, a table and a chart. The permission matrix moves into
Postgres row-level security, so even SQL written by an LLM can't see outside its scope, including
support's "only the ticket's student".
