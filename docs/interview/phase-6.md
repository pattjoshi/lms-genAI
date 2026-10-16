# Interview prep: Phase 6 (text-to-SQL agent, scoped and read-only)

Same format: **approach → why → 2 alternatives → cross-questions → real-world example.**
"How do you let an LLM query a database safely?" is a standard GenAI system-design question. A good answer
puts security in the database, not in the prompt, and still makes the agent good at SQL.

---

## 0. "How does your SQL agent work?" (60 seconds)

> "A question goes to a small LangGraph state machine. Step one is one structured LLM call that returns
> answerable, SQL and a note. The prompt has the schema read from Postgres comments, six few-shot examples,
> and who is asking, but no security rules: the database does that.
>
> The SQL is parsed with sqlglot: exactly one SELECT, only our 11 tables, no writes anywhere in the tree,
> no system functions. A failure goes back to the model with the exact error, up to three tries, except a
> write, which is refused at once.
>
> Then it runs as a separate Postgres login that only has SELECT, in a read-only transaction with a
> statement timeout and a row limit. Row-level security policies, generated from our permission matrix,
> filter the rows: a student sees their own records, a teacher only their own courses' students. The
> policies know who is asking through a table keyed by the connection's backend pid, which a query can't
> change, unlike a session setting. Finally a second call writes a short answer from the rows, and code
> picks the chart from the result's shape."

---

## 1. Where do you enforce permissions for LLM-written SQL?

**Approach used:** in Postgres: a read-only login plus row-level security. The prompt only says who is
asking so "my" resolves.

**Why:** the model is not a security boundary. A rule in the prompt ("only query the user's own rows")
is one injection away from being ignored; a policy is evaluated for every row whatever the SQL says.

**Alternative 1: the app adds the WHERE clause** (rewrite the AST to inject `student_id = :me`).
- ✅ Works on any database, no RLS needed.
- ❌ You must find every table reference, including subqueries, CTEs, and joins through other tables; miss
  one and data leaks. RLS does it in the planner for you.

**Alternative 2: views or a semantic layer** (the model queries `my_scores`, `my_payments` views or a
metrics API instead of tables).
- ✅ Smaller, safer surface; names the model understands.
- ❌ Every new question needs a view; less flexible. Good for a product with known questions.

**Cross-questions:**
- *Does RLS slow queries down?* The policy is an extra predicate per row; with our helper functions it's
  a primary-key lookup. At millions of rows you'd index the columns the policies filter on and keep the
  functions `STABLE` so the planner can hoist them.
- *Why not trust `current_setting('app.user_id')`?* The query can call `set_config` itself. See 3.

---

## 2. How do you make sure it can never write?

**Approach used:** three independent locks: no write grants, `default_transaction_read_only` on the role
plus `SET TRANSACTION READ ONLY`, and the validator refusing any write node. Plus `statement_timeout` and a
LIMIT wrapper so a read can't take the database down either.

**Why a separate login, not `SET ROLE`:** `SET ROLE` can be undone from inside a query
(`set_config('role', 'none', false)`), going back to the owner. A login has nothing to go back to.

**Alternative: a read replica.** Writes are physically impossible and heavy queries don't touch the
primary. ✅ Best for production analytics. ❌ Still needs RLS or a per-tenant replica for scope, plus
replication lag. I'd add it, not replace RLS with it.

---

## 3. How do the RLS policies know the user?

**Approach used:** before each query the app (owner) writes `(pid, user_id, role)` into a table the reader
can't read; `SECURITY DEFINER` functions look it up with `pg_backend_pid()`. Deleted afterwards; an
unregistered connection sees nothing.

**Alternative 1: session setting** (`SET app.user_id`). Standard for app-written SQL, unsafe for
model-written SQL: the query can change it.

**Alternative 2: one database role per user** (`SET ROLE riya`, `current_user` in policies). Unforgeable
too, but thousands of roles to manage, and roles are cluster-wide.

**Alternative 3: signed setting** (an HMAC of the user id the policy verifies with a server secret).
Works with PgBouncer transaction pooling, where the pid trick doesn't. More crypto to get right.

---

## 4. How do you make the SQL good?

- **Schema-aware prompt** from the live database: comments carry meaning (thresholds, enum values).
- **Few-shot examples** in the house style: names not ids, rounding, ILIKE, date_trunc, time zone.
- **Self-correction** with the real error message, bounded attempts, every attempt logged.
- **A way out**: `answerable=false` so it doesn't invent a query.

**Cross-questions:**
- *500 tables?* Schema retrieval: embed table descriptions, put the top 10 in the prompt; or a two-step
  "pick tables, then write SQL".
- *How do you evaluate it?* A set of question → expected result pairs (our seed stories); compare result
  sets, not SQL strings, because many queries are correct. That's Phase 7.
- *Why not let it retry forever?* Cost and loops. Three tries fix most errors; beyond that the question is
  usually ambiguous and a person should rephrase.

---

## 5. Why is the chart chosen by code?

The result's shape decides (one number, time + numbers, category + numbers). Free, deterministic,
testable, and it can't reference a missing column. An LLM adds value when intent matters ("share" →
stacked bar, "compare to last year" → two series); you'd let it suggest and have code validate.

---

## 6. Real-world examples

- **Snowflake Cortex Analyst, Databricks Genie:** text-to-SQL over a semantic model, running with the
  user's own warehouse permissions (row access policies), never a shared superuser.
- **Supabase:** RLS policies on `auth.uid()` from a signed JWT, the "signed setting" design above.
- **LangChain SQL agent:** schema + few-shot + "query checker" + retry on error, the same loop; its
  docs warn to use a read-only user scoped to the minimum, which is our layers 3 and 4.
