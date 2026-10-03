"use client";

// Ask a doubt: the RAG answer streams in token by token, with the retrieved
// course excerpts shown as numbered sources ([1], [2] in the answer).

import { BookOpen, Bot, FileText, Info, MessageSquarePlus, Send, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { Alert, Button, Card, Chip, EmptyState } from "@/components/ui";
import { useApi } from "@/components/useApi";
import { apiFetch, ApiError } from "@/lib/api";
import { streamSSE } from "@/lib/sse";

type Source = {
  rank: number;
  score: number;
  used: boolean;
  text: string;
  file_name: string;
  file_type: string;
  page: number | null;
  section: string | null;
  topic: string | null;
  course_code: string;
};

type Done = {
  status: "answered" | "no_context";
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  embed_tokens: number;
  cost_usd: number;
  latency_ms: number;
  first_token_ms: number;
  attempts: number;
  top_score: number | null;
};

type Turn = {
  question: string;
  answer: string;
  sources: Source[];
  minScore: number;
  done?: Done;
  error?: { code: string; message: string };
};

type HistoryItem = { id: number; question: string; status: string; created_at: string };

const SUGGESTIONS = [
  "How does backpropagation compute gradients?",
  "What is the chain rule, with an example?",
  "Why does my model overfit, and how do I fix it?",
  "What's the difference between a list and a tuple?",
];

function where(s: Source) {
  return s.page ? `page ${s.page}` : (s.section ?? "");
}

/** Render "[1]" markers in the answer as small numbered badges. */
function AnswerText({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
      {parts.map((part, i) =>
        /^\[\d+\]$/.test(part) ? (
          <sup
            key={i}
            className="mx-0.5 rounded bg-brand-soft px-1 py-px font-mono text-[10px] font-semibold text-brand-ink"
          >
            {part.slice(1, -1)}
          </sup>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </p>
  );
}

function SourceCard({ source, number }: { source: Source; number?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className={`rounded-xl border p-3 text-sm ${source.used ? "border-line bg-surface" : "border-dashed border-line opacity-60"}`}
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
        <span className="font-mono text-xs text-muted" title="Cosine similarity to your question">
          {source.score.toFixed(2)}
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

function SourceList({ numbered }: { numbered: { s: Source; number?: number }[] }) {
  const [showWeak, setShowWeak] = useState(false);
  const used = numbered.filter((x) => x.number);
  const weak = numbered.filter((x) => !x.number);
  return (
    <div>
      {used.length > 0 && (
        <>
          <p className="mb-2 text-xs font-medium text-muted">Sources from your course material</p>
          <div className="grid gap-2 md:grid-cols-2">
            {used.map(({ s, number }) => (
              <SourceCard key={s.rank} source={s} number={number} />
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
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {weak.map(({ s }) => (
            <SourceCard key={s.rank} source={s} />
          ))}
        </div>
      )}
    </div>
  );
}

function TurnView({ turn, streaming }: { turn: Turn; streaming: boolean }) {
  let n = 0;
  const numbered = turn.sources.map((s) => ({ s, number: s.used ? ++n : undefined }));
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
              <AnswerText text={turn.answer} />
            ) : (
              <p className="text-sm text-muted">
                {turn.sources.length ? "Writing the answer…" : "Searching your course material…"}
              </p>
            )}
            {turn.done?.status === "no_context" && (
              <p className="mt-2 flex items-center gap-1.5 text-xs text-warn">
                <Info className="h-3.5 w-3.5" /> No relevant material found (best match{" "}
                {turn.done.top_score?.toFixed(2) ?? "–"} &lt; {turn.minScore}). The AI was not asked, so it
                couldn&apos;t guess.
              </p>
            )}
          </div>
          {turn.error && <Alert title={`${turn.error.message} (${turn.error.code})`} />}

          {turn.sources.length > 0 && <SourceList numbered={numbered} />}

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

function AskDoubt() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const finished = turns.filter((t) => t.done || t.error).length;
  const history = useApi<HistoryItem[]>(`/chat/history?limit=8&v=${finished}-${historyVersion}`);

  // Braces matter: newer browsers return a Promise from scrollIntoView(), and an effect
  // must return nothing (or a cleanup function).
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function removeDoubt(id?: number) {
    if (id === undefined && !confirm("Remove all your doubts from your history?")) return;
    await apiFetch(id === undefined ? "/chat/history" : `/chat/history/${id}`, { method: "DELETE" }).catch(() => null);
    setHistoryVersion((v) => v + 1);
  }

  function update(fn: (t: Turn) => Turn) {
    setTurns((all) => [...all.slice(0, -1), fn(all[all.length - 1])]);
  }

  async function ask(text: string) {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setQuestion("");
    setTurns((all) => [...all, { question: q, answer: "", sources: [], minScore: 0 }]);
    try {
      await streamSSE("/chat/ask", { question: q }, (event, data) => {
        if (event === "sources") update((t) => ({ ...t, sources: data.sources, minScore: data.min_score }));
        else if (event === "token") update((t) => ({ ...t, answer: t.answer + data.text }));
        else if (event === "done") update((t) => ({ ...t, done: data }));
        else if (event === "error") update((t) => ({ ...t, error: data }));
      });
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
        subtitle="Answers come only from the material of your enrolled courses, with sources"
        icon={<Sparkles className="h-4 w-4" />}
        action={
          turns.length > 0 && (
            <Button variant="ghost" onClick={() => setTurns([])} disabled={busy} title="Start a new chat">
              <MessageSquarePlus className="h-4 w-4" />
              <span className="hidden sm:inline">New chat</span>
            </Button>
          )
        }
      >
        <div className="space-y-6">
          {turns.length === 0 && (
            <div className="rounded-xl bg-surface-2/60 p-4">
              <p className="text-sm text-muted">Try one of these:</p>
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
            <TurnView key={i} turn={t} streaming={busy && i === turns.length - 1} />
          ))}
          <div ref={bottom} />

          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(question);
            }}
            className="sticky bottom-4 flex gap-2 rounded-2xl border border-line bg-surface p-2 shadow-card"
          >
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={1000}
              placeholder="Ask about anything in your courses…"
              className="flex-1 bg-transparent px-3 py-2 text-sm text-fg placeholder:text-faint focus:outline-none"
            />
            <Button type="submit" disabled={busy || question.trim().length < 3} aria-label="Ask">
              <Send className="h-4 w-4" />
              <span className="hidden sm:inline">{busy ? "Answering…" : "Ask"}</span>
            </Button>
          </form>
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
