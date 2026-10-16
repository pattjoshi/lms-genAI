"use client";

// Phase 6: "Ask the data", the same page in every portal. A question in plain English goes to the SQL
// agent (POST /sql/ask); the answer comes back with the SQL it ran (and any attempts it fixed), a chart
// picked from the shape of the result, and the rows. What each role sees is decided by the database
// (row-level security), so the page itself has no role logic beyond the example questions.

import { ChartColumn, ChevronDown, Database, History, LockKeyhole, Send, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

import { type Cell, type ChartSpec, DataChart, formatValue, label } from "@/components/DataChart";
import { Alert, Button, Card, Chip, EmptyState, SkeletonCard } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";
import type { Role } from "@/lib/session";

type Attempt = { sql: string | null; error: string | null; stage: string };
type ScopeRow = { data: string; scope: string };

type Answer = {
  id: number;
  question: string;
  status: "answered" | "no_rows" | "refused" | "failed";
  sql: string | null;
  attempts: Attempt[];
  answer: string | null;
  note?: string;
  chart: ChartSpec | null;
  columns?: string[];
  rows?: Cell[][];
  row_count: number;
  truncated: boolean;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  llm_calls?: number;
  query_ms?: number | null;
  created_at: string | null;
};

type Scope = { role: Role; scope: ScopeRow[]; ready: boolean; error: string | null };

const EXAMPLES: Record<Role, string[]> = {
  student: [
    "What is my average quiz score per course?",
    "Which topics am I weakest in?",
    "Show my payments",
    "What did Ananya Iyer score in Backpropagation?",
  ],
  teacher: [
    "Which topics do my students fail most?",
    "Students in my courses with an average score below 50",
    "Average quiz score per week in my courses",
    "Show Arjun Mehta's payments",
  ],
  support: [
    "Which students have an open ticket, and what are their failed payments?",
    "Failed logins of students with an open ticket",
    "How many tickets were opened per day?",
    "List all students and their cities",
  ],
  admin: [
    "Revenue per month",
    "Drop-out rate per course",
    "Which topics have the lowest average score?",
    "Failed payments in the last 30 days",
    "AI cost per feature",
    "Delete all failed payments",
  ],
};

const STATUS: Record<Answer["status"], { text: string; style: string }> = {
  answered: { text: "Answered", style: "border-ok/30 bg-ok-soft text-ok" },
  no_rows: { text: "No rows", style: "border-line bg-surface-2 text-muted" },
  refused: { text: "Refused", style: "border-warn/30 bg-warn-soft text-warn" },
  failed: { text: "Couldn't answer", style: "border-bad/30 bg-bad-soft text-bad" },
};

const STAGE: Record<string, string> = {
  check: "refused by the SQL checker",
  run: "Postgres error",
  timeout: "too slow",
  setup: "database setup",
};

function StatusBadge({ status }: { status: Answer["status"] }) {
  const s = STATUS[status];
  return <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${s.style}`}>{s.text}</span>;
}

function SqlBlock({ sql }: { sql: string }) {
  return (
    <pre className="overflow-x-auto rounded-xl border border-line bg-surface-2 p-3 font-mono text-xs leading-relaxed text-fg">
      {sql}
    </pre>
  );
}

function Attempts({ attempts }: { attempts: Attempt[] }) {
  const failed = attempts.filter((a) => a.error);
  if (failed.length === 0) return null;
  return (
    <details className="rounded-xl border border-line p-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm text-fg">
        <Wrench className="h-4 w-4 text-muted" />
        {failed.length} failed attempt{failed.length === 1 ? "" : "s"} before this
        <ChevronDown className="ml-auto h-4 w-4 text-muted" />
      </summary>
      <ol className="mt-3 space-y-3">
        {failed.map((a, i) => (
          <li key={i} className="space-y-1.5">
            <p className="text-xs text-muted">
              Attempt {attempts.indexOf(a) + 1}: {STAGE[a.stage] ?? a.stage}:{" "}
              <span className="font-mono text-bad">{a.error}</span>
            </p>
            {a.sql && <SqlBlock sql={a.sql} />}
          </li>
        ))}
      </ol>
    </details>
  );
}

function ResultTable({ columns, rows }: { columns: string[]; rows: Cell[][] }) {
  return (
    <div className="max-h-96 overflow-auto rounded-xl border border-line">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-surface-2 text-xs text-muted">
          <tr>
            {columns.map((c, i) => (
              <th
                key={i}
                className={`whitespace-nowrap px-3 py-2 font-medium ${typeof rows[0]?.[i] === "number" ? "text-right" : ""}`}
              >
                {label(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="border-t border-line">
              {r.map((v, ci) => (
                <td
                  key={ci}
                  className={`whitespace-nowrap px-3 py-1.5 ${typeof v === "number" ? "text-right tabular-nums" : ""} text-fg`}
                >
                  {formatValue(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Result({ a }: { a: Answer }) {
  const columns = a.columns ?? [];
  const rows = a.rows ?? [];
  return (
    <div className="space-y-5">
      <Card>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={a.status} />
            <p className="text-sm text-muted">“{a.question}”</p>
          </div>
          <p className="text-[15px] leading-relaxed text-fg">{a.answer}</p>
          {a.note && <p className="text-xs text-muted">Assumption: {a.note}</p>}
          <div className="flex flex-wrap gap-1.5">
            {a.status !== "refused" && a.status !== "failed" && (
              <Chip>
                {a.row_count} row{a.row_count === 1 ? "" : "s"}
                {a.truncated ? " (cut off)" : ""}
              </Chip>
            )}
            {a.llm_calls !== undefined && <Chip>{a.llm_calls} AI calls</Chip>}
            <Chip mono>
              {a.input_tokens + a.output_tokens} tokens · ${a.cost_usd.toFixed(5)}
            </Chip>
            <Chip mono>
              {a.latency_ms} ms{a.query_ms != null ? ` (query ${a.query_ms} ms)` : ""}
            </Chip>
          </div>
        </div>
      </Card>

      {a.chart && rows.length > 0 && (
        <Card title="Chart" subtitle={`Picked from the shape of the result: ${a.chart.type}`} icon={<ChartColumn className="h-4 w-4" />}>
          <DataChart spec={a.chart} columns={columns} rows={rows} />
        </Card>
      )}

      {(a.sql || a.attempts.length > 0) && (
        <Card
          title="SQL"
          subtitle="Written by the AI, checked, then run as a read-only database user that only sees your rows."
          icon={<Database className="h-4 w-4" />}
        >
          <div className="space-y-3">
            {a.sql && <SqlBlock sql={a.sql} />}
            <Attempts attempts={a.attempts} />
          </div>
        </Card>
      )}

      {columns.length > 0 && rows.length > 0 && (
        <Card title="Rows" subtitle={a.truncated ? "Only the first rows; the rest were cut off." : undefined}>
          <ResultTable columns={columns} rows={rows} />
        </Card>
      )}
    </div>
  );
}

function ScopePanel({ scope }: { scope: Scope }) {
  return (
    <details className="group rounded-xl border border-line p-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm text-fg">
        <LockKeyhole className="h-4 w-4 text-muted" />
        What your role ({scope.role}) can see
        <ChevronDown className="ml-auto h-4 w-4 text-muted transition-transform group-open:rotate-180" />
      </summary>
      <ul className="mt-3 grid gap-1.5 text-sm sm:grid-cols-2">
        {scope.scope.map((s) => (
          <li key={s.data} className="flex justify-between gap-3 rounded-lg bg-surface-2/60 px-2.5 py-1.5">
            <span className="text-muted">{s.data}</span>
            <span className={s.scope === "none" ? "text-faint" : "font-medium text-fg"}>{s.scope}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-faint">
        Enforced by the database (row-level security), not by the AI: asking differently doesn&apos;t change it.
      </p>
    </details>
  );
}

export function AskData({ role }: { role: Role }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [scope, setScope] = useState<Scope | null>(null);
  const [history, setHistory] = useState<Answer[]>([]);

  const loadHistory = () =>
    apiFetch<Answer[]>("/sql/history")
      .then(setHistory)
      .catch(() => undefined);

  useEffect(() => {
    apiFetch<Scope>("/sql/scope")
      .then(setScope)
      .catch(() => undefined);
    loadHistory();
  }, []);

  const ask = async (q: string) => {
    const text = q.trim();
    if (text.length < 3 || busy) return;
    setQuestion(text);
    setBusy(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await apiFetch<Answer>("/sql/ask", { method: "POST", body: JSON.stringify({ question: text }) }));
      loadHistory();
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_18rem]">
      <div className="min-w-0 space-y-5">
        <Card
          title="Ask about the data"
          subtitle="Plain English in; an answer, a chart and the SQL out. The AI can read data, never change it."
          icon={<ChartColumn className="h-4 w-4" />}
        >
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              ask(question);
            }}
          >
            <div className="flex gap-2">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={500}
                placeholder={EXAMPLES[role][0]}
                className="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg outline-none focus:border-brand focus:ring-2 focus:ring-[var(--ring)]"
              />
              <Button type="submit" disabled={busy || question.trim().length < 3}>
                <Send className="h-4 w-4" />
                {busy ? "Thinking" : "Ask"}
              </Button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES[role].map((q) => (
                <button
                  key={q}
                  type="button"
                  disabled={busy}
                  onClick={() => ask(q)}
                  className="rounded-full border border-line px-2.5 py-1 text-xs text-muted hover:border-brand hover:text-fg disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
            {scope && <ScopePanel scope={scope} />}
            {scope && !scope.ready && (
              <Alert title="The SQL agent isn't set up on the server." detail={scope.error ?? undefined} />
            )}
          </form>
        </Card>

        {error && <Alert title={error.message} detail={error.detail} />}
        {busy && <SkeletonCard lines={4} />}
        {answer && <Result a={answer} />}
      </div>

      <Card title="Your recent questions" icon={<History className="h-4 w-4" />} className="h-fit">
        {history.length === 0 ? (
          <EmptyState title="Nothing yet" hint="Questions you ask show up here." />
        ) : (
          <ul className="space-y-2">
            {history.map((h) => (
              <li key={h.id}>
                <button
                  onClick={() => ask(h.question)}
                  disabled={busy}
                  title="Ask again"
                  className="w-full rounded-xl border border-line p-2.5 text-left hover:bg-surface-2 disabled:opacity-50"
                >
                  <p className="line-clamp-2 text-sm text-fg">{h.question}</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <StatusBadge status={h.status} />
                    {h.attempts.filter((a) => a.error).length > 0 && (
                      <span className="text-[11px] text-faint">self-corrected</span>
                    )}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
