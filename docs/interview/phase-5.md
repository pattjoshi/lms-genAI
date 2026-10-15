# Interview prep: Phase 5 (tickets, human in the loop, knowledge feedback)

Same format: **approach → why → 2 alternatives → cross-questions → real-world example.**
"What happens when your AI is wrong?" is the question every GenAI interview gets to. A good answer has a
detection signal, a human path, and a way the fix flows back into the system.

---

## 0. "What happens when your AI can't answer?" (60 seconds)

> "It says so, and a person takes over. Four free signals open a ticket: retrieval found nothing relevant,
> the answer's confidence was low (the best source only just passed the relevance threshold), the student
> pressed thumbs down, or the message was a login or payment problem. One ticket per message.
>
> Support gets a context package: the question, the query that was actually searched after rewriting, every
> passage with its score, the AI's draft and confidence, and the student's records, but only while the
> ticket is open. They edit the draft and resolve.
>
> A resolved course answer goes into a knowledge base: the question vector and the answer. Retrieval
> compares every new question with it, and a near-paraphrase (cosine 0.80+) becomes source [1], labelled
> as verified. So the same question never needs a person twice. No fine-tuning: it's live on resolve,
> scoped by course, and can be withdrawn. Teachers see the questions grouped by meaning, so the gaps go back
> into the course material."

---

## 1. How do you decide which answers a human should see?

**Approach used:** signals we already compute: no relevant retrieval, low confidence from retrieval scores,
👎, and the intent (account problems). No extra LLM call.

**Why:** a person can't read every answer, and the signals are free and explainable ("ticket because the
best passage scored 0.27 against a 0.25 threshold").

**Alternative 1: an LLM judge on every answer** (faithfulness / "is this supported by the sources?").
- ✅ Catches confident wrong answers that retrieval scores can't see.
- ❌ Doubles the cost, adds latency, and the judge has its own errors and biases.
- **I'd use it** sampled (say 5% of answers) or offline in evaluation, which is Phase 7.

**Alternative 2: only user feedback.**
- ✅ The truest signal: the reader says it didn't help.
- ❌ Most people never click. Silence isn't approval.
- **What I did:** both. Free automatic triggers plus 👎.

**Cross-questions:**
- *"Won't every off-topic question become a ticket?"* Yes, that's the cost of the `no_answer` trigger. It has
  a flag, and an off-topic guardrail (Phase 7) removes most of them before retrieval.
- *"Isn't low confidence just a retrieval score?"* Yes, and that's what it is honest about: how well the
  material matched, not whether the generated text is faithful.

---

## 2. What do you give the human?

**Approach used:** a context package built from what the chat already stored: question, searched query,
passages with scores (text read back by document id and chunk index), the AI draft, confidence, route,
👎 comment, and only the student records this kind of ticket needs.

**Why:** a person who has to ask the student again, or re-run the search, is slower than no AI at all.

**Cross-questions:**
- *"Why store the searched query?"* Follow-ups are rewritten. "give an example" alone tells support nothing.
- *"Why not store the passage text on the ticket?"* It's already in `chunks`; storing ids keeps rows small and
  shows the current text. If a file was replaced, the ticket still has the file name and score.

---

## 3. How do you limit what support can see?

**Approach used:** the permission matrix's `TICKET_STUDENT` scope: a student's records only through a ticket,
only while it is open; payments only for a payment ticket, logins only for a login ticket. Admins: all.

**Alternative: support sees every student, with an audit log.**
- ✅ Simpler, and sometimes needed (a call centre).
- ❌ Everyone in support can browse anyone's payments. An audit log tells you after the fact.
- **I'd use it** with a "break glass" button that requires a reason and alerts a lead.

**Cross-question:** *"Where is the rule?"* In one function (`can_see_records`) used by the ticket detail. In
Phase 6 the same rule moves into Postgres row-level security, so even LLM-written SQL can't bypass it.

---

## 4. How does the AI "learn" from support?

**Approach used:** retrieval-time knowledge feedback. Resolved course answers become knowledge-base entries
(question vector + answer + course). Retrieval step 7 reuses the query vector, finds entries at cosine ≥ 0.80
in the student's courses, and puts them first, labelled *Support answer (verified)*.

**Alternative 1: fine-tune on resolved tickets.**
- ✅ The model itself knows the answer, no retrieval needed.
- ❌ Hours to train, can't remove one bad answer, can't scope by course or student, needs hundreds of
  examples to matter, and the model can still paraphrase it wrong.
- **I'd use it** for tone and format (how to answer), never for facts that change.

**Alternative 2: add the answer as a new chunk in the course index.**
- ✅ One search path; the reranker scores it like any chunk.
- ❌ Mixed in with teacher material, harder to label as verified, harder to withdraw; a general passage
  could outrank the exact answer.
- **What I did:** a separate, higher threshold and a separate label, so the student and the teacher can see
  where the answer came from.

**Cross-questions:**
- *"Why 0.80 when chunks use 0.25?"* A chunk is general material; a support answer answers one question.
  Close-but-different questions ("what is X" vs "why does X work") must not reuse it.
- *"What if support saves a wrong answer?"* It's scoped to one course, labelled, and withdrawn in one click.
  The ticket keeps who wrote it.
- *"Login answers?"* Never saved: they're about one person. The server refuses, not only the checkbox.

**Real-world example:** customer support platforms (Zendesk, Intercom) suggest past resolved answers to
agents and feed approved ones into their AI bots' knowledge base; the human-approved article is the unit, not
model weights.

---

## 5. Why not a vector database for these vectors?

**Approach used:** Postgres JSON columns, cosine in Python.

**Why:** hundreds of knowledge-base entries and a few thousand questions: a Python loop is milliseconds.
Resolving a ticket and creating its knowledge-base entry is one transaction. Filters are SQL.

**Alternative: pgvector or a second Qdrant collection.**
- ✅ Indexed search (HNSW), scales to millions.
- ❌ Qdrant: a second store to keep in sync with the ticket (what if one write fails?). pgvector: an
  extension to install, still worth it at scale.
- **I'd switch** at ~50k vectors or when search latency shows up in traces. pgvector first: same transaction.

---

## 6. How do you find the most asked questions?

**Approach used:** embed each question once (kept on the row), then greedy leader clustering: each question
joins the most similar group centre at cosine ≥ 0.80, or starts a new group. Centre = running sum of vectors.
Label = the member closest to the centre. Gaps = the same over unanswered, low-confidence and 👎 questions.

**Alternative 1: k-means.** ❌ You must choose k, and every outlier is forced into a cluster.
**Alternative 2: HDBSCAN.** ✅ Finds k and noise. ❌ A dependency and parameters that are hard to explain to a
teacher. **I'd use it** at thousands of questions per course.

**Cross-questions:**
- *"Why is the sum the same as the mean?"* Cosine ignores length; sum and mean point the same way.
- *"Order dependence?"* Greedy clustering can put a borderline question in either group. For counts on a
  dashboard that's acceptable; the threshold is the knob people understand.
- *"Privacy?"* Teachers see questions and counts, never names.

---

## 7. An MCP tool that writes

**Approach used:** `create_ticket` returns a preview unless `confirm=true`, and says "ask the user first".
Students only. The in-chat assistant doesn't get the tool (it can't ask mid-turn).

**Cross-question:** *"Can't the model just pass confirm=true?"* Yes. Confirmation by contract relies on the
client showing the call to the user (Claude Desktop asks before tool calls). The server-side guarantees are
the role check, the rate limit and the audit log; anything destructive would need a real second factor.

---

## Rapid-fire

| Question | Answer |
|---|---|
| Human in the loop vs human on the loop? | In: a person acts before the outcome (resolve). On: a person monitors and can intervene (insights) |
| Why one ticket per message? | Duplicates waste support time; a 👎 updates the existing ticket |
| When is a ticket's vector computed? | When support first opens it: chat never waits, unopened tickets cost nothing |
| Knowledge base threshold? | 0.80: near-paraphrases only |
| Similar tickets threshold? | 0.75: lower, because a person reads the result |
| Fine-tuning vs retrieval for new facts? | Retrieval: instant, scoped, removable, citable |
| What does support never see? | Records of a student without an open ticket, and payments on a course question |

---

## Mistakes to avoid

1. Saying "the model learns from feedback" when it's retrieval. Be precise; interviewers check.
2. Escalating without context, so the human redoes the AI's work.
3. Saving every resolution to the knowledge base, including one person's account details.
4. A similarity threshold copied from chunk search for exact-question reuse.
5. A thumbs-down button that does nothing visible. Show the student that a person will look.
