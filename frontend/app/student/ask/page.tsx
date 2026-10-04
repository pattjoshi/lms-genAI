"use client";

// Ask a doubt: the RAG answer streams in token by token, with the retrieved
// course excerpts shown as numbered sources ([1], [2] in the answer).
// Phase 2: follow-up questions (one conversation id per chat), "Search in" filters,
// and a "Show details" panel that explains how the sources were found.

import {
  BookOpen,
  Bot,
  FileText,
  Filter,
  Info,
  MessageSquarePlus,
  Microscope,
  Send,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { Alert, Button, Card, Chip, EmptyState } from "@/components/ui";
import { useApi } from "@/components/useApi";
import { apiFetch, ApiError } from "@/lib/api";
import { streamSSE } from "@/lib/sse";

type Source = {
  rank: number;
  score: number | null; // cosine similarity; null = found by keyword search only
  dense_rank: number | null;
  keyword_rank: number | null;
  rrf: number | null;
  rerank_score: number | null;
  used: boolean;
  text: string;
  file_name: string;
  file_type: string;
  page: number | null;
  section: string | null;
  topic: string | null;
  course_code: string;
};

type Relevance = { by: "rerank" | "cosine"; best: number | null; threshold: number };

type Details = {
  question: string;
  query: string;
  rewritten: boolean;
  retried_with: string | null;
  retry_tried: string | null;
  hybrid: boolean;
  rerank: boolean;
  reranked: boolean;
  rerank_error: string | null;
  rewrite: boolean;
  corrective: boolean;
  module_id: number | null;
  relevance: Relevance;
  timings_ms: Record<string, number>;
  llm_cost_usd: number;
  warnings: string[];
};

type Done = {
  status: "answered" | "no_context";
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  embed_tokens: number;
  cost_usd: number;
  retrieval_cost_usd: number;
  latency_ms: number;
  first_token_ms: number;
  attempts: number;
  top_score: number | null;
  relevance: Relevance;
};

type Turn = {
  question: string;
  answer: string;
  sources: Source[];
  details?: Details;
  done?: Done;
  error?: { code: string; message: string };
};

type HistoryItem = { id: number; question: string; status: string; created_at: string };
type ScopeCourse = { id: number; code: string; title: string; modules: { id: number; position: number; title: string }[] };

const SUGGESTIONS = [
  "How does backpropagation compute gradients?",
  "What is the chain rule, with an example?",
  "Why does my model overfit, and how do I fix it?",
  "What's the difference between a list and a tuple?",
];

const DETAILS_KEY = "lms.ask.showDetails";

function newConversationId(): string {
  // crypto.randomUUID needs a secure context (https or localhost); fall back just in case.
  return globalThis.crypto?.randomUUID?.() ?? `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function where(s: Source) {
  return s.page ? `page ${s.page}` : (s.section ?? "");
}

function fmt(x: number | null | undefined, digits = 2) {
  return x === null || x === undefined ? "–" : x.toFixed(digits);
}

/** Render "[1]" markers in the answer as small numbered buttons that jump to the source. */
function AnswerText({ text, onCite }: { text: string; onCite: (n: number) => void }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
      {parts.map((part, i) =>
        /^\[\d+\]$/.test(part) ? (
          <button
            key={i}
            onClick={() => onCite(Number(part.slice(1, -1)))}
            title={`Show source ${part}`}
            aria-label={`Source ${part.slice(1, -1)}`}
            className="mx-0.5 -translate-y-1 rounded bg-brand-soft px-1 py-px align-baseline font-mono text-[10px] font-semibold text-brand-ink hover:bg-brand hover:text-brand-fg"
          >
            {part.slice(1, -1)}
          </button>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </p>
  );
}

function SourceCard({
  source,
  number,
  anchor,
  highlight,
}: {
  source: Source;
  number?: number;
  anchor?: string;
  highlight?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const reranked = source.rerank_score !== null;
  const score = reranked ? source.rerank_score : source.score;
  return (
    <div
      id={anchor}
      className={`scroll-mt-24 rounded-xl border p-3 text-sm transition-shadow ${
        source.used ? "border-line bg-surface" : "border-dashed border-line opacity-60"
      } ${highlight ? "ring-2 ring-brand" : ""}`}
    >
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-start gap-2.5 text-left">
        <span
          className={`mt-0.5 flex h-5 min-w-5 items-center justify-center rounded font-mono text-[11px] font-semibold ${
            number ? "bg-brand-soft text-brand-ink" : "bg-surface-2 text-faint"
          }`}
        >
          {number ?? "–"}
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 truncate font-medium text-fg">
            <FileText className="h-3.5 w-3.5 shrink-0 text-muted" />
            <span className="truncate">{source.file_name}</span>
          </p>
          <p className="mt-0.5 text-xs text-muted">
            {source.course_code} · {where(source)}
            {source.topic && source.topic !== where(source) && ` · ${source.topic}`}
          </p>
        </div>
        <span
          className="font-mono text-xs text-muted"
          title={
            reranked
              ? "Reranker relevance (0–1): how well this excerpt answers your question"
              : score === null
                ? "Found by keyword search"
                : "Cosine similarity to your question"
          }
        >
          {score === null ? "kw" : score.toFixed(2)}
        </span>
      </button>
      {!source.used && (
        <p className="mt-1.5 pl-7 text-xs text-faint">Below the relevance threshold, not given to the AI</p>
      )}
      {open && (
        <p className="mt-2 whitespace-pre-wrap rounded-lg bg-surface-2 p-2.5 text-xs text-muted">{source.text}</p>
      )}
    </div>
  );
}

type Numbered = { s: Source; number?: number };

function SourceList({ numbered, anchor, active }: { numbered: Numbered[]; anchor: (n: number) => string; active: number | null }) {
  const [showWeak, setShowWeak] = useState(false);
  const used = numbered.filter((x) => x.number);
  const weak = numbered.filter((x) => !x.number);
  return (
    <div>
      {used.length > 0 && (
        <>
          <p className="mb-2 text-xs font-medium text-muted">Sources from your course material</p>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {used.map(({ s, number }) => (
              <SourceCard key={s.rank} source={s} number={number} anchor={anchor(number!)} highlight={active === number} />
            ))}
          </div>
        </>
      )}
      {weak.length > 0 && (
        <button onClick={() => setShowWeak((v) => !v)} className="mt-2 text-xs text-faint hover:text-muted">
          {showWeak ? "Hide" : "Show"} {weak.length} below-threshold match{weak.length > 1 ? "es" : ""}
        </button>
      )}
      {showWeak && (
        <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
          {weak.map(({ s }) => (
            <SourceCard key={s.rank} source={s} />
          ))}
        </div>
      )}
    </div>
  );
}

/** "How this answer was found": the Phase 2 pipeline, step by step, for this question. */
function DetailsPanel({ details, numbered }: { details: Details; numbered: Numbered[] }) {
  const t = details.timings_ms;
  const step = (on: boolean, label: string, extra?: string) => (
    <Chip mono>
      <span className={on ? "text-ok" : "text-faint"}>{on ? "✓" : "–"}</span> {label}
      {extra && <span className="text-faint">{extra}</span>}
    </Chip>
  );
  return (
    <div className="rounded-xl border border-line bg-surface-2/50 p-3 text-xs">
      <p className="mb-2 flex items-center gap-1.5 font-medium text-fg">
        <Microscope className="h-3.5 w-3.5 text-brand-ink" /> How this answer was found
      </p>
      <dl className="space-y-1 text-muted">
        <div className="flex gap-2">
          <dt className="w-24 shrink-0 text-faint">Searched for</dt>
          <dd className="text-fg">
            “{details.retried_with ?? details.query}”
            {details.rewritten && <span className="ml-1.5 text-brand-ink">(follow-up rewritten using the chat)</span>}
            {details.retried_with && <span className="ml-1.5 text-brand-ink">(corrective retry)</span>}
          </dd>
        </div>
        {details.retry_tried && !details.retried_with && (
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-faint">Also tried</dt>
            <dd>“{details.retry_tried}” (found nothing better)</dd>
          </div>
        )}
        <div className="flex gap-2">
          <dt className="w-24 shrink-0 text-faint">Relevance</dt>
          <dd>
            by {details.relevance.by === "rerank" ? "reranker score" : "cosine similarity"}, best{" "}
            {fmt(details.relevance.best)}, threshold {details.relevance.threshold}
          </dd>
        </div>
      </dl>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {step(details.rewrite, "rewrite", t.rewrite !== undefined ? ` ${t.rewrite}ms` : "")}
        {step(details.hybrid, "hybrid (meaning + keywords)")}
        {step(details.reranked, "rerank", t.rerank !== undefined && details.reranked ? ` ${t.rerank}ms` : "")}
        {step(details.corrective, "corrective retry", t.retry !== undefined ? ` ${t.retry}ms` : "")}
        <Chip mono>embed {t.embed ?? 0}ms · search {t.search ?? 0}ms</Chip>
        {details.llm_cost_usd > 0 && <Chip mono>rewrite ${details.llm_cost_usd.toFixed(6)}</Chip>}
      </div>
      {details.warnings.map((w) => (
        <p key={w} className="mt-2 text-warn">
          {w}
        </p>
      ))}
      {numbered.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[480px] text-left font-mono text-[11px]">
            <thead className="text-faint">
              <tr>
                <th className="py-1 pr-2 font-medium">#</th>
                <th className="py-1 pr-2 font-medium">topic</th>
                <th className="py-1 pr-2 font-medium" title="Rank in the meaning (embedding) search">
                  meaning
                </th>
                <th className="py-1 pr-2 font-medium" title="Rank in the keyword (BM25) search">
                  keyword
                </th>
                <th className="py-1 pr-2 font-medium" title="Cosine similarity">
                  cosine
                </th>
                <th className="py-1 pr-2 font-medium" title="Reranker relevance 0–1">
                  rerank
                </th>
                <th className="py-1 font-medium">used</th>
              </tr>
            </thead>
            <tbody className="text-muted">
              {numbered.map(({ s, number }) => (
                <tr key={s.rank} className="border-t border-line">
                  <td className="py-1 pr-2">{number ?? "–"}</td>
                  <td className="max-w-[180px] truncate py-1 pr-2 font-sans">{s.topic ?? where(s)}</td>
                  <td className="py-1 pr-2">{s.dense_rank ?? "–"}</td>
                  <td className="py-1 pr-2">{s.keyword_rank ?? "–"}</td>
                  <td className="py-1 pr-2">{fmt(s.score)}</td>
                  <td className="py-1 pr-2">{fmt(s.rerank_score, 3)}</td>
                  <td className={`py-1 ${s.used ? "text-ok" : "text-faint"}`}>{s.used ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TurnView({
  turn,
  index,
  streaming,
  showDetails,
}: {
  turn: Turn;
  index: number;
  streaming: boolean;
  showDetails: boolean;
}) {
  const [active, setActive] = useState<number | null>(null);
  let n = 0;
  const numbered = turn.sources.map((s) => ({ s, number: s.used ? ++n : undefined }));
  const anchor = (num: number) => `turn-${index}-source-${num}`;

  function cite(num: number) {
    document.getElementById(anchor(num))?.scrollIntoView({ behavior: "smooth", block: "center" });
    setActive(num);
    setTimeout(() => setActive(null), 1600);
  }

  const relevance = turn.done?.relevance;
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-sm text-brand-fg">
          {turn.question}
        </p>
      </div>
      <div className="flex gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-ink">
          <Bot className={`h-4 w-4 ${streaming ? "animate-pulse" : ""}`} />
        </span>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-3">
            {turn.answer ? (
              <AnswerText text={turn.answer} onCite={cite} />
            ) : (
              <p className="text-sm text-muted">
                {turn.details ? "Writing the answer…" : "Searching your course material…"}
              </p>
            )}
            {turn.details?.rewritten && !showDetails && (
              <p className="mt-2 text-xs text-faint">Understood as: “{turn.details.query}”</p>
            )}
            {turn.done?.status === "no_context" && relevance && (
              <p className="mt-2 flex items-start gap-1.5 text-xs text-warn">
                <Info className="mt-px h-3.5 w-3.5 shrink-0" />
                <span>
                  No relevant material found (best {relevance.by === "rerank" ? "reranker score" : "match"}{" "}
                  {fmt(relevance.best)} &lt; {relevance.threshold}
                  {turn.details?.retry_tried && <>, also searched for “{turn.details.retry_tried}”</>}). The AI was
                  not asked, so it couldn&apos;t guess.
                </span>
              </p>
            )}
          </div>
          {turn.error && <Alert title={`${turn.error.message} (${turn.error.code})`} />}

          {turn.sources.length > 0 && <SourceList numbered={numbered} anchor={anchor} active={active} />}

          {showDetails && turn.details && <DetailsPanel details={turn.details} numbered={numbered} />}

          {turn.done && (
            <div className="flex flex-wrap gap-1.5">
              {turn.done.model && <Chip mono>{turn.done.model}</Chip>}
              <Chip mono>
                {turn.done.input_tokens} in / {turn.done.output_tokens} out
              </Chip>
              <Chip mono>{turn.done.embed_tokens} embed</Chip>
              <Chip mono>${turn.done.cost_usd.toFixed(6)}</Chip>
              {turn.done.first_token_ms > 0 && <Chip mono>first token {turn.done.first_token_ms} ms</Chip>}
              <Chip mono>total {turn.done.latency_ms} ms</Chip>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** "Search in": narrow the search to one course or module (the server only ever narrows). */
function ScopePicker({
  courses,
  courseId,
  moduleId,
  onChange,
  disabled,
}: {
  courses: ScopeCourse[];
  courseId: number | null;
  moduleId: number | null;
  onChange: (courseId: number | null, moduleId: number | null) => void;
  disabled: boolean;
}) {
  const course = courses.find((c) => c.id === courseId);
  const select =
    "min-w-0 rounded-lg border border-line bg-surface px-2 py-1 text-xs text-fg focus:outline-none focus:ring-2 focus:ring-[var(--ring)]";
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
      <Filter className="h-3.5 w-3.5" />
      <span>Search in</span>
      <select
        aria-label="Course"
        className={select}
        disabled={disabled}
        value={courseId ?? ""}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null, null)}
      >
        <option value="">All my courses</option>
        {courses.map((c) => (
          <option key={c.id} value={c.id}>
            {c.code} · {c.title}
          </option>
        ))}
      </select>
      {course && (
        <select
          aria-label="Module"
          className={select}
          disabled={disabled}
          value={moduleId ?? ""}
          onChange={(e) => onChange(course.id, e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">All modules</option>
          {course.modules.map((m) => (
            <option key={m.id} value={m.id}>
              M{m.position} · {m.title}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

function AskDoubt() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  // One id per chat: the server uses earlier questions of the same chat to understand follow-ups.
  const [conversationId, setConversationId] = useState<string>(() => newConversationId());
  const [courseId, setCourseId] = useState<number | null>(null);
  const [moduleId, setModuleId] = useState<number | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const finished = turns.filter((t) => t.done || t.error).length;
  const history = useApi<HistoryItem[]>(`/chat/history?limit=8&v=${finished}-${historyVersion}`);
  const scope = useApi<ScopeCourse[]>("/chat/scope");

  // A per-browser preference only; storage can be unavailable (private mode), so guard it.
  useEffect(() => {
    try {
      setShowDetails(localStorage.getItem(DETAILS_KEY) === "1");
    } catch {}
  }, []);

  function toggleDetails() {
    setShowDetails((v) => {
      try {
        localStorage.setItem(DETAILS_KEY, v ? "0" : "1");
      } catch {}
      return !v;
    });
  }

  // Braces matter: newer browsers return a Promise from scrollIntoView(), and an effect
  // must return nothing (or a cleanup function).
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  async function removeDoubt(id?: number) {
    if (id === undefined && !confirm("Remove all your doubts from your history?")) return;
    await apiFetch(id === undefined ? "/chat/history" : `/chat/history/${id}`, { method: "DELETE" }).catch(() => null);
    setHistoryVersion((v) => v + 1);
  }

  function newChat() {
    setTurns([]);
    setConversationId(newConversationId());
  }

  function update(fn: (t: Turn) => Turn) {
    setTurns((all) => [...all.slice(0, -1), fn(all[all.length - 1])]);
  }

  async function ask(text: string) {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setQuestion("");
    setTurns((all) => [...all, { question: q, answer: "", sources: [] }]);
    try {
      await streamSSE(
        "/chat/ask",
        { question: q, conversation_id: conversationId, course_id: courseId, module_id: moduleId },
        (event, data) => {
          if (event === "sources") update((t) => ({ ...t, sources: data.sources, details: data.retrieval }));
          else if (event === "token") update((t) => ({ ...t, answer: t.answer + data.text }));
          else if (event === "done") update((t) => ({ ...t, done: data }));
          else if (event === "error") update((t) => ({ ...t, error: data }));
        },
      );
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "unknown", String(e));
      update((t) => ({ ...t, error: { code: err.code, message: err.message } }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_280px]">
      <Card
        title="Ask a doubt"
        subtitle="Answers come only from the material of your enrolled courses, with sources. Follow-up questions work."
        icon={<Sparkles className="h-4 w-4" />}
        // min-w-0: a grid column won't shrink below its content's width (long file names) otherwise
        className="min-w-0"
        action={
          <div className="flex shrink-0 gap-2">
            <Button
              variant="ghost"
              onClick={toggleDetails}
              aria-pressed={showDetails}
              title="Show how each answer was found"
              className={showDetails ? "border-brand/50 text-brand-ink" : ""}
            >
              <Microscope className="h-4 w-4" />
              <span className="hidden sm:inline">{showDetails ? "Hide details" : "Show details"}</span>
            </Button>
            {turns.length > 0 && (
              <Button variant="ghost" onClick={newChat} disabled={busy} title="Start a new chat (forgets the context)">
                <MessageSquarePlus className="h-4 w-4" />
                <span className="hidden sm:inline">New chat</span>
              </Button>
            )}
          </div>
        }
      >
        <div className="space-y-6">
          {turns.length === 0 && (
            <div className="rounded-xl bg-surface-2/60 p-4">
              <p className="text-sm text-muted">Try one of these, then ask a follow-up like “can you give an example?”</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => ask(s)}
                    className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-fg hover:border-brand/50 hover:text-brand-ink"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t, i) => (
            <TurnView
              key={i}
              turn={t}
              index={i}
              streaming={busy && i === turns.length - 1}
              showDetails={showDetails}
            />
          ))}
          <div ref={bottom} />

          <div className="sticky bottom-4 space-y-2 rounded-2xl border border-line bg-surface p-2 shadow-card">
            {!!scope.data?.length && (
              <div className="px-2 pt-1">
                <ScopePicker
                  courses={scope.data}
                  courseId={courseId}
                  moduleId={moduleId}
                  disabled={busy}
                  onChange={(c, m) => {
                    setCourseId(c);
                    setModuleId(m);
                  }}
                />
              </div>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask(question);
              }}
              className="flex gap-2"
            >
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={1000}
                placeholder={turns.length ? "Ask a follow-up or a new question…" : "Ask about anything in your courses…"}
                className="min-w-0 flex-1 bg-transparent px-3 py-2 text-sm text-fg placeholder:text-faint focus:outline-none"
              />
              <Button type="submit" disabled={busy || question.trim().length < 3} aria-label="Ask">
                <Send className="h-4 w-4" />
                <span className="hidden sm:inline">{busy ? "Answering…" : "Ask"}</span>
              </Button>
            </form>
          </div>
        </div>
      </Card>

      <Card
        title="Recent doubts"
        icon={<BookOpen className="h-4 w-4" />}
        className="h-fit"
        action={
          !!history.data?.length && (
            <button onClick={() => removeDoubt()} className="text-xs text-faint hover:text-bad" title="Clear history">
              Clear all
            </button>
          )
        }
      >
        {!history.data?.length ? (
          <EmptyState title="No doubts yet" />
        ) : (
          <ul className="space-y-1">
            {history.data.map((h) => (
              <li key={h.id} className="group flex items-start gap-1 rounded-lg hover:bg-surface-2">
                <button
                  onClick={() => ask(h.question)}
                  disabled={busy}
                  className="min-w-0 flex-1 px-2 py-1.5 text-left text-sm text-fg"
                  title="Ask again"
                >
                  <span className="line-clamp-2">{h.question}</span>
                  <span
                    className={`text-xs ${h.status === "answered" ? "text-ok" : h.status === "no_context" ? "text-warn" : "text-bad"}`}
                  >
                    {h.status.replace("_", " ")}
                  </span>
                </button>
                <button
                  onClick={() => removeDoubt(h.id)}
                  className="mt-1.5 mr-1 rounded-md p-1 text-faint opacity-60 hover:bg-bad-soft hover:text-bad group-hover:opacity-100"
                  title="Remove from history"
                  aria-label={`Remove "${h.question}" from history`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function AskPage() {
  return (
    <PortalShell role="student" title="Ask a doubt" showRoadmap={false}>
      {() => <AskDoubt />}
    </PortalShell>
  );
}
