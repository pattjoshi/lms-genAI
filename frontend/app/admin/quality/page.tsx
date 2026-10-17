"use client";

// Phase 7: "AI quality & cost" for the admin. Cost (A4), latency (A5), answer quality with the eval runs (A6, A8),
// links into Langfuse (A7) and the guardrail log (A9). Everything comes from GET /quality/* (our own tables);
// evals are run from the command line (`uv run python -m app.evals.answers`) and show up here.

import { Activity, CircleDollarSign, ExternalLink, FlaskConical, Gauge, ShieldAlert, Timer } from "lucide-react";
import { useState } from "react";

import { type Cell, DataChart } from "@/components/DataChart";
import { PortalShell } from "@/components/PortalShell";
import { Alert, Card, Chip, EmptyState, ProgressBar, SkeletonCard, Stat } from "@/components/ui";
import { useApi } from "@/components/useApi";

type Latency = { p50: number | null; p95: number | null; max: number | null };
type Group = Latency & {
  calls: number;
  errors: number;
  retried: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  feature?: string;
  role?: string;
  model?: string;
};
type EvalSummary = Record<string, number | null>;
type EvalRun = {
  id: number;
  created_at: string | null;
  label: string | null;
  config: Record<string, unknown>;
  summary: EvalSummary;
  cost_usd: number;
};

type Dashboard = {
  days: number;
  budget: { spent_today_usd: number; daily_budget_usd: number };
  usage: {
    calls: number;
    errors: number;
    retried: number;
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
    projected_month_usd: number;
    per_day: { day: string; cost_usd: number; calls: number; errors: number; p95_ms: number | null }[];
    by_feature: Group[];
    by_role: Group[];
    by_model: Group[];
    errors_by_code: Record<string, number>;
  };
  chat: {
    messages: number;
    latency: Latency;
    first_token: Latency;
    cost_per_message_usd: number | null;
    per_day: { day: string; messages: number; p50_ms: number | null; p95_ms: number | null }[];
    by_intent: Record<string, number>;
    quality: {
      course_questions: number;
      answered: number;
      no_answer_rate: number | null;
      low_confidence_rate: number | null;
      blocked: number;
      errors: number;
      thumbs_up: number;
      thumbs_down: number;
      satisfaction: number | null;
      checked_answers: number;
      valid_citations_rate: number | null;
      avg_citation_coverage: number | null;
      flagged_answers: number;
    };
  };
  guardrails: { blocked: number; flagged: number; by_kind: Record<string, number> };
  evals: EvalRun[];
  langfuse: { enabled: boolean; base_url: string | null };
};

type CompareRow = {
  metric: string;
  label: string;
  before: number | null;
  now: number | null;
  change: number | null;
  verdict: string;
};
type EvalItem = {
  id: string;
  expect: string;
  question: string;
  answered: boolean;
  guard?: string | null;
  context_precision?: number;
  context_recall?: number;
  faithfulness?: number | null;
  relevance?: number;
  correctness?: number;
  reason?: string;
  trace_url?: string | null;
};
type Evals = {
  run: (EvalRun & { items: EvalItem[]; judge_checks: { id: string; expect: string; passed: boolean }[] }) | null;
  baseline: EvalRun | null;
  compare: CompareRow[];
};

type GuardEvent = {
  id: number;
  at: string | null;
  user: string | null;
  role: string | null;
  surface: string;
  stage: string;
  kind: string;
  action: string;
  method: string;
  text: string;
  detail: { reason?: string; similarity?: number | null; rule?: string };
};

type Call = {
  id: number;
  at: string;
  feature: string;
  latency_ms: number;
  cost_usd: number;
  tokens: number;
  attempts: number;
  status: string;
  trace_url: string | null;
};
type Traces = {
  langfuse: boolean;
  recent: {
    id: number;
    at: string | null;
    user: string;
    question: string;
    intent: string | null;
    status: string;
    latency_ms: number;
    cost_usd: number;
    trace_url: string | null;
  }[];
  slowest: Call[];
  priciest: Call[];
};

const usd = (v: number, digits = 4) => `$${v.toFixed(digits)}`;
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
const ms = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`;
const time = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" }) : "");

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface-2/70 text-xs text-muted">
          <tr>
            {head.map((h) => (
              <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

const td = "px-3 py-2";
const tdMono = "px-3 py-2 font-mono text-xs";

function TraceLink({ url }: { url: string | null | undefined }) {
  if (!url) return <span className="text-faint">–</span>;
  return (
    <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-ink hover:underline">
      trace <ExternalLink className="h-3 w-3" />
    </a>
  );
}

function Trend({ rows, column }: { rows: Record<string, Cell>[]; column: string }) {
  const data = rows.filter((r) => r[column] !== null);
  if (data.length < 2) return <p className="text-xs text-faint">Not enough days with data for a chart yet.</p>;
  return <DataChart spec={{ type: "line", x: "day", y: [column] }} columns={["day", column]} rows={data.map((r) => [r.day, r[column]])} />;
}

// --- cost ------------------------------------------------------------------

function CostCard({ d }: { d: Dashboard }) {
  const u = d.usage;
  const usedPct = Math.min(100, (d.budget.spent_today_usd / Math.max(d.budget.daily_budget_usd, 1e-9)) * 100);
  return (
    <Card
      title="Cost"
      subtitle={`Every LLM and embedding call in the last ${d.days} day${d.days > 1 ? "s" : ""} (llm_usage).`}
      icon={<CircleDollarSign className="h-4 w-4" />}
    >
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Spent" value={usd(u.cost_usd)} mono />
        <Stat label="Calls" value={u.calls.toLocaleString("en-IN")} hint={`${u.errors} errors · ${u.retried} retried`} />
        <Stat label="Tokens in / out" value={`${u.input_tokens.toLocaleString("en-IN")} / ${u.output_tokens.toLocaleString("en-IN")}`} mono />
        <Stat label="A month at this pace" value={usd(u.projected_month_usd, 2)} mono />
      </div>
      <div className="mt-4 flex items-center gap-3">
        <span className="text-xs text-muted">Today</span>
        <div className="flex-1">
          <ProgressBar value={usedPct} tone={usedPct >= 80 ? "bg-bad" : usedPct >= 50 ? "bg-warn" : "bg-ok"} />
        </div>
        <span className="font-mono text-xs text-muted">
          {usd(d.budget.spent_today_usd)} / {usd(d.budget.daily_budget_usd, 2)}
        </span>
      </div>
      <div className="mt-5">
        <p className="mb-2 text-xs font-medium text-muted">Cost per day (USD)</p>
        <Trend rows={u.per_day} column="cost_usd" />
      </div>
      <div className="mt-5">
        <p className="mb-2 text-xs font-medium text-muted">By feature (most expensive first)</p>
        {u.by_feature.length === 0 ? (
          <EmptyState title="No AI calls in this window" />
        ) : (
          <Table head={["Feature", "Calls", "Tokens in / out", "Cost", "p50", "p95", "Errors", "Retried"]}>
            {u.by_feature.map((g) => (
              <tr key={g.feature}>
                <td className={td}>{g.feature}</td>
                <td className={tdMono}>{g.calls}</td>
                <td className={tdMono}>
                  {g.input_tokens} / {g.output_tokens}
                </td>
                <td className={tdMono}>{usd(g.cost_usd, 6)}</td>
                <td className={tdMono}>{ms(g.p50)}</td>
                <td className={tdMono}>{ms(g.p95)}</td>
                <td className={tdMono}>{g.errors || ""}</td>
                <td className={tdMono}>{g.retried || ""}</td>
              </tr>
            ))}
          </Table>
        )}
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {u.by_role.map((g) => (
          <Chip key={g.role} mono>
            {g.role}: {usd(g.cost_usd)}
          </Chip>
        ))}
        {u.by_model.map((g) => (
          <Chip key={g.model} mono>
            {g.model}: {usd(g.cost_usd)}
          </Chip>
        ))}
      </div>
    </Card>
  );
}

// --- latency ---------------------------------------------------------------

function LatencyCard({ d }: { d: Dashboard }) {
  const c = d.chat;
  const errors = Object.entries(d.usage.errors_by_code);
  return (
    <Card
      title="Latency"
      subtitle="p50 = the typical request, p95 = 1 in 20 is slower than this. The average hides the slow tail."
      icon={<Timer className="h-4 w-4" />}
    >
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Chat message p50" value={ms(c.latency.p50)} mono hint={`${c.messages} messages`} />
        <Stat label="Chat message p95" value={ms(c.latency.p95)} mono hint={`slowest ${ms(c.latency.max)}`} />
        <Stat label="First token p50" value={ms(c.first_token.p50)} mono hint="what the student feels" />
        <Stat label="First token p95" value={ms(c.first_token.p95)} mono />
      </div>
      <div className="mt-5">
        <p className="mb-2 text-xs font-medium text-muted">Chat p95 per day (ms)</p>
        <Trend rows={c.per_day} column="p95_ms" />
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {Object.entries(c.by_intent).map(([k, v]) => (
          <Chip key={k} mono>
            {k}: {v}
          </Chip>
        ))}
        {errors.map(([k, v]) => (
          <span key={k} className="rounded-full bg-bad-soft px-2 py-0.5 font-mono text-xs text-bad">
            {k}: {v}
          </span>
        ))}
      </div>
    </Card>
  );
}

// --- quality ---------------------------------------------------------------

const VERDICT_STYLE: Record<string, string> = { better: "text-ok", worse: "text-bad", same: "text-muted" };

function fmtMetric(metric: string, v: number | null) {
  if (v === null || v === undefined) return "–";
  if (metric === "avg_ms") return ms(v);
  if (metric === "cost_usd") return usd(v);
  if (metric === "over_blocked") return String(v);
  return v.toFixed(2);
}

function QualityCard({ d }: { d: Dashboard }) {
  const q = d.chat.quality;
  const { data: evals } = useApi<Evals>("/quality/evals");
  const [open, setOpen] = useState(false);
  return (
    <Card
      title="Answer quality"
      subtitle="Live: feedback and code checks on every answer. Offline: the eval set, graded by an LLM judge."
      icon={<FlaskConical className="h-4 w-4" />}
    >
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="👍 / 👎" value={`${q.thumbs_up} / ${q.thumbs_down}`} hint={`satisfaction ${pct(q.satisfaction)}`} />
        <Stat label="No answer found" value={pct(q.no_answer_rate)} hint={`of ${q.course_questions} course questions`} />
        <Stat label="Low confidence" value={pct(q.low_confidence_rate)} hint={`of ${q.answered} answers`} />
        <Stat
          label="Valid citations"
          value={pct(q.valid_citations_rate)}
          hint={`${pct(q.avg_citation_coverage)} of sentences cited · ${q.flagged_answers} flagged`}
        />
      </div>

      <div className="mt-5">
        <p className="mb-2 text-xs font-medium text-muted">Eval runs</p>
        {!evals ? (
          <SkeletonCard lines={2} />
        ) : !evals.run ? (
          <EmptyState
            title="No eval run yet"
            hint="Run it from backend/: uv run python -m app.evals.answers (about $0.03). Each run is compared with the previous one."
          />
        ) : (
          <>
            <p className="mb-2 text-sm text-fg">
              Run #{evals.run.id}
              {evals.run.label && <> · {evals.run.label}</>} · {time(evals.run.created_at)}
              {evals.baseline && (
                <span className="text-muted">
                  {" "}
                  compared with #{evals.baseline.id}
                  {evals.baseline.label && <> ({evals.baseline.label})</>}
                </span>
              )}
            </p>
            <Table head={["Metric", "Before", "Now", "Verdict"]}>
              {(evals.compare.length
                ? evals.compare
                : Object.entries(evals.run.summary)
                    .filter(([k]) => k !== "questions")
                    .map(([k, v]) => ({ metric: k, label: k.replace(/_/g, " "), before: null, now: v, change: null, verdict: "-" }))
              ).map((r) => (
                <tr key={r.metric}>
                  <td className={td}>{r.label}</td>
                  <td className={tdMono}>{fmtMetric(r.metric, r.before)}</td>
                  <td className={tdMono}>{fmtMetric(r.metric, r.now)}</td>
                  <td className={`${td} text-xs font-medium ${VERDICT_STYLE[r.verdict] ?? "text-faint"}`}>{r.verdict}</td>
                </tr>
              ))}
            </Table>
            <button onClick={() => setOpen(!open)} className="mt-3 text-xs font-medium text-brand-ink hover:underline">
              {open ? "Hide" : "Show"} scores per question
            </button>
            {open && (
              <div className="mt-2">
                <Table head={["Id", "Question", "Context P / R", "Faithful", "Relevant", "Correct", "Trace"]}>
                  {evals.run.items.map((i) => (
                    <tr key={i.id}>
                      <td className={tdMono}>{i.id}</td>
                      <td className={`${td} max-w-xs`} title={i.reason}>
                        {i.question}
                        {i.expect !== "answer" && (
                          <span className={`ml-1 text-xs ${(i.expect === "no_answer" ? !i.answered : !!i.guard) ? "text-ok" : "text-bad"}`}>
                            ({i.expect}: {i.guard ? `refused, ${i.guard}` : i.answered ? "answered" : "not answered"})
                          </span>
                        )}
                      </td>
                      <td className={tdMono}>
                        {i.context_precision !== undefined ? `${i.context_precision.toFixed(2)} / ${i.context_recall?.toFixed(2)}` : ""}
                      </td>
                      <td className={tdMono}>{i.faithfulness?.toFixed(2) ?? ""}</td>
                      <td className={tdMono}>{i.relevance?.toFixed(2) ?? ""}</td>
                      <td className={tdMono}>{i.correctness === undefined ? "" : i.correctness ? "yes" : "no"}</td>
                      <td className={td}>
                        <TraceLink url={i.trace_url} />
                      </td>
                    </tr>
                  ))}
                </Table>
                {evals.run.judge_checks.length > 0 && (
                  <p className="mt-2 text-xs text-muted">
                    Judge checks:{" "}
                    {evals.run.judge_checks.map((c) => `${c.id} (${c.expect}) ${c.passed ? "passed" : "FAILED"}`).join(" · ")}
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

// --- guardrails ------------------------------------------------------------

const KIND_LABEL: Record<string, string> = {
  injection: "prompt injection",
  off_topic: "off topic",
  invalid_citation: "made-up citation",
  uncited: "uncited answer",
  prompt_leak: "prompt leak",
  email: "email in answer",
};

function GuardrailCard({ d }: { d: Dashboard }) {
  const { data, error } = useApi<GuardEvent[]>("/quality/guardrails?limit=50");
  return (
    <Card
      title="Guardrail log"
      subtitle="Messages refused before answering, and answers flagged after. Messages that pass aren't logged."
      icon={<ShieldAlert className="h-4 w-4" />}
    >
      <div className="mb-4 flex flex-wrap gap-1.5">
        <Chip mono>blocked {d.guardrails.blocked}</Chip>
        <Chip mono>flagged {d.guardrails.flagged}</Chip>
        {Object.entries(d.guardrails.by_kind).map(([k, v]) => (
          <Chip key={k} mono>
            {k}: {v}
          </Chip>
        ))}
      </div>
      {error ? (
        <Alert title={error.message} />
      ) : !data ? (
        <SkeletonCard lines={3} />
      ) : data.length === 0 ? (
        <EmptyState title="Nothing refused or flagged yet" hint="Ask the chat about cricket, or to print its system prompt." />
      ) : (
        <Table head={["Time", "Who", "What", "Action", "How", "Message"]}>
          {data.map((e) => (
            <tr key={e.id}>
              <td className={`${tdMono} whitespace-nowrap`}>{time(e.at)}</td>
              <td className={td}>
                {e.user ?? "–"} <span className="text-xs text-faint">{e.surface}</span>
              </td>
              <td className={td}>{KIND_LABEL[e.kind] ?? e.kind}</td>
              <td className={td}>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    e.action === "blocked" ? "bg-bad-soft text-bad" : "bg-warn-soft text-warn"
                  }`}
                >
                  {e.action}
                </span>
              </td>
              <td className={`${td} text-xs text-muted`} title={e.detail.reason}>
                {e.method}
                {e.detail.rule && ` · ${e.detail.rule}`}
                {e.method === "llm" && e.detail.reason && ` · “${e.detail.reason}”`}
              </td>
              <td className={`${td} max-w-sm truncate`} title={e.text}>
                {e.text}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

// --- traces ----------------------------------------------------------------

function CallTable({ calls }: { calls: Call[] }) {
  return (
    <Table head={["Time", "Feature", "Latency", "Cost", "Tokens", "Attempts", "Trace"]}>
      {calls.map((c) => (
        <tr key={c.id}>
          <td className={`${tdMono} whitespace-nowrap`}>{time(c.at)}</td>
          <td className={td}>
            {c.feature} {c.status === "error" && <span className="text-xs text-bad">error</span>}
          </td>
          <td className={tdMono}>{ms(c.latency_ms)}</td>
          <td className={tdMono}>{usd(c.cost_usd, 6)}</td>
          <td className={tdMono}>{c.tokens}</td>
          <td className={tdMono}>{c.attempts}</td>
          <td className={td}>
            <TraceLink url={c.trace_url} />
          </td>
        </tr>
      ))}
    </Table>
  );
}

function TracesCard({ days }: { days: number }) {
  const { data, error } = useApi<Traces>(`/quality/traces?days=${days}`);
  return (
    <Card
      title="Traces"
      subtitle="Open a request in Langfuse to see every step: guardrail, routing, retrieval, the prompt and the answer."
      icon={<Activity className="h-4 w-4" />}
    >
      {error ? (
        <Alert title={error.message} />
      ) : !data ? (
        <SkeletonCard lines={3} />
      ) : (
        <div className="space-y-5">
          {!data.langfuse && (
            <Alert
              title="Langfuse is not configured, so there are no trace links."
              detail="Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env and restart the backend. Everything else on this page works without it."
            />
          )}
          <div>
            <p className="mb-2 text-xs font-medium text-muted">Latest chat messages</p>
            <Table head={["Time", "Who", "Message", "Intent", "Status", "Latency", "Cost", "Trace"]}>
              {data.recent.map((r) => (
                <tr key={r.id}>
                  <td className={`${tdMono} whitespace-nowrap`}>{time(r.at)}</td>
                  <td className={td}>{r.user}</td>
                  <td className={`${td} max-w-xs truncate`} title={r.question}>
                    {r.question}
                  </td>
                  <td className={`${td} text-xs`}>{r.intent ?? "doubt"}</td>
                  <td className={`${td} text-xs`}>{r.status}</td>
                  <td className={tdMono}>{ms(r.latency_ms)}</td>
                  <td className={tdMono}>{usd(r.cost_usd, 6)}</td>
                  <td className={td}>
                    <TraceLink url={r.trace_url} />
                  </td>
                </tr>
              ))}
            </Table>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-muted">Slowest LLM calls</p>
            <CallTable calls={data.slowest} />
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-muted">Most expensive LLM calls</p>
            <CallTable calls={data.priciest} />
          </div>
        </div>
      )}
    </Card>
  );
}

// --- page ------------------------------------------------------------------

function QualityDashboard() {
  const [days, setDays] = useState(7);
  const { data, error } = useApi<Dashboard>(`/quality/dashboard?days=${days}`);
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Gauge className="h-4 w-4 text-muted" />
        <span className="text-sm text-muted">Window:</span>
        {[1, 7, 30].map((n) => (
          <button
            key={n}
            onClick={() => setDays(n)}
            className={`rounded-lg px-3 py-1 text-sm ${
              days === n ? "bg-brand-soft font-medium text-brand-ink" : "text-muted hover:bg-surface-2"
            }`}
          >
            {n === 1 ? "Today" : `${n} days`}
          </button>
        ))}
      </div>
      {error ? (
        <Alert title={error.message} detail={error.detail} />
      ) : !data ? (
        <>
          <SkeletonCard lines={4} />
          <SkeletonCard lines={4} />
        </>
      ) : (
        <>
          <CostCard d={data} />
          <LatencyCard d={data} />
          <QualityCard d={data} />
          <GuardrailCard d={data} />
          <TracesCard days={days} />
        </>
      )}
    </>
  );
}

export default function Page() {
  return (
    <PortalShell role="admin" title="AI quality & cost" showRoadmap={false}>
      {() => <QualityDashboard />}
    </PortalShell>
  );
}
