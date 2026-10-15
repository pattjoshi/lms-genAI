"use client";

// Phase 5: the ticket queue (P1) and one ticket's full context (P3), for support and admins.
// Left: the queue with filters. Right: the selected ticket, what the AI saw and said, the student
// (only while the ticket is open, P8), similar resolved tickets (P7), and the answer editor (P4-P6).

import {
  BookCheck,
  Bot,
  CircleUser,
  History,
  Inbox,
  Search,
  Send,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import {
  ago,
  REASON_LABEL,
  STATUS_LABEL,
  StatusPill,
  Tag,
  type TicketRow,
} from "@/components/tickets";
import { Alert, Button, Card, EmptyState, SkeletonCard } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";
import type { Role } from "@/lib/session";

type Queue = { counts: Record<string, number>; tickets: TicketRow[] };

type ChatSource = {
  rank: number;
  score: number | null;
  rerank_score: number | null;
  used: boolean;
  file_name: string;
  page: number | null;
  section: string | null;
  course_code: string | null;
  text: string | null;
};

type Detail = TicketRow & {
  draft: string | null;
  course_id: number | null;
  kb_allowed: boolean;
  chat: {
    question: string;
    search_query: string | null;
    answer: string | null;
    status: string;
    intent: string | null;
    route: { method?: string; confidence?: number } | null;
    confidence: string | null;
    top_score: number | null;
    top_rerank_score: number | null;
    feedback: number | null;
    feedback_comment: string | null;
    sources: ChatSource[];
    asked_at: string | null;
  } | null;
  student_context: {
    visible: boolean;
    name?: string;
    note?: string;
    email?: string;
    city?: string;
    enrollments?: {
      code: string;
      title: string;
      status: string;
      progress_pct: number;
    }[];
    payments?: {
      course_code: string;
      amount_inr: number;
      status: string;
      method: string;
      failure_reason: string | null;
      at: string;
    }[];
    logins?: {
      at: string;
      success: boolean;
      reason: string | null;
      device: string;
    }[];
  };
  similar: {
    available: boolean;
    tickets: {
      id: number;
      subject: string;
      resolution: string;
      similarity: number;
    }[];
  };
};

type Course = { id: number; code: string; title: string };

const select =
  "rounded-lg border border-line bg-surface px-2 py-1 text-xs text-fg focus:outline-none focus:ring-2 focus:ring-[var(--ring)]";

function err(e: unknown) {
  return e instanceof ApiError ? e : new ApiError(0, "unknown", String(e));
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-faint">
        {icon}
        {title}
      </p>
      {children}
    </div>
  );
}

function Context({ d }: { d: Detail }) {
  const c = d.chat;
  if (!c)
    return (
      <p className="text-sm text-muted">
        Opened by the student, not from a chat message.
      </p>
    );
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap gap-1.5">
        <Tag>status {c.status}</Tag>
        {c.intent && <Tag>intent {c.intent}</Tag>}
        {c.confidence && <Tag>confidence {c.confidence}</Tag>}
        {c.top_rerank_score !== null && (
          <Tag>best rerank {c.top_rerank_score.toFixed(2)}</Tag>
        )}
        {c.top_score !== null && (
          <Tag>best cosine {c.top_score.toFixed(2)}</Tag>
        )}
        {c.feedback === -1 && (
          <Tag>👎{c.feedback_comment ? `: “${c.feedback_comment}”` : ""}</Tag>
        )}
      </div>
      {c.search_query && (
        <p className="text-xs text-muted">Searched for: “{c.search_query}”</p>
      )}
      <div className="rounded-xl bg-surface-2 p-3">
        <p className="mb-1 text-xs font-medium text-muted">
          What the AI answered
        </p>
        <p className="whitespace-pre-wrap text-fg">{c.answer || "(nothing)"}</p>
      </div>
      {c.sources.length > 0 && (
        <details className="rounded-xl border border-line p-3">
          <summary className="cursor-pointer text-xs font-medium text-muted">
            Passages the AI read ({c.sources.filter((s) => s.used).length} used
            of {c.sources.length})
          </summary>
          <div className="mt-2 space-y-2">
            {c.sources.map((s) => (
              <div
                key={s.rank}
                className={`text-xs ${s.used ? "" : "opacity-60"}`}
              >
                <p className="font-medium text-fg">
                  {s.file_name}{" "}
                  {s.page
                    ? `· page ${s.page}`
                    : s.section
                      ? `· ${s.section}`
                      : ""}{" "}
                  <span className="font-mono text-faint">
                    {s.rerank_score !== null
                      ? `rerank ${s.rerank_score.toFixed(2)}`
                      : s.score !== null
                        ? `cos ${s.score.toFixed(2)}`
                        : ""}
                    {s.used ? " · used" : " · not used"}
                  </span>
                </p>
                {s.text && (
                  <p className="mt-0.5 line-clamp-4 whitespace-pre-wrap text-muted">
                    {s.text}
                  </p>
                )}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function Student({ s }: { s: Detail["student_context"] }) {
  if (!s.visible) {
    return (
      <p className="text-sm text-muted">
        {s.name && <span className="font-medium text-fg">{s.name}. </span>}
        {s.note}
      </p>
    );
  }
  return (
    <div className="space-y-2 text-sm">
      <p className="text-fg">
        <span className="font-medium">{s.name}</span>{" "}
        <span className="text-muted">
          · {s.email} · {s.city}
        </span>
      </p>
      <div className="flex flex-wrap gap-1.5">
        {s.enrollments?.map((e) => (
          <Tag key={e.code}>
            {e.code} {e.status} {e.progress_pct}%
          </Tag>
        ))}
      </div>
      {s.payments && (
        <ul className="space-y-0.5 text-xs text-muted">
          {s.payments.map((p, i) => (
            <li key={i}>
              {p.course_code}: ₹{p.amount_inr} by {p.method},{" "}
              <span className="text-fg">{p.status}</span>
              {p.failure_reason && ` (${p.failure_reason})`}, {ago(p.at)}
            </li>
          ))}
        </ul>
      )}
      {s.logins && (
        <ul className="space-y-0.5 text-xs text-muted">
          {s.logins.map((l, i) => (
            <li key={i}>
              {ago(l.at)} on {l.device}:{" "}
              <span className={l.success ? "text-ok" : "text-bad"}>
                {l.success ? "ok" : "failed"}
              </span>
              {l.reason && ` (${l.reason.replaceAll("_", " ")})`}
            </li>
          ))}
        </ul>
      )}
      <p className="text-[11px] text-faint">
        Shown only while this ticket is open.
      </p>
    </div>
  );
}

function TicketPanel({
  id,
  courses,
  onChanged,
}: {
  id: number;
  courses: Course[];
  onChanged: () => void;
}) {
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [answer, setAnswer] = useState("");
  const [toKb, setToKb] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const x = await apiFetch<Detail>(`/tickets/${id}`);
      setD(x);
      setAnswer(x.resolution ?? x.draft ?? "");
      setToKb(x.kb_allowed); // P6: on for course questions, off (and locked) for account problems
    } catch (e) {
      setError(err(e));
    }
  }, [id]);

  useEffect(() => {
    setD(null);
    load();
  }, [load]);

  async function act(path: string, body?: object) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/tickets/${id}/${path}`, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      await load();
      onChanged();
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }

  if (!d)
    return error ? (
      <Alert title={error.message} detail={error.detail} />
    ) : (
      <SkeletonCard lines={8} />
    );
  const resolved = d.status === "resolved";
  return (
    <Card>
      <div className="space-y-5">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={d.status} />
            <span className="font-mono text-xs text-faint">#{d.id}</span>
            <Tag>{REASON_LABEL[d.reason] ?? d.reason}</Tag>
            <Tag>{d.category}</Tag>
            <span className="text-xs text-faint">{ago(d.created_at)}</span>
            {d.assigned_to && (
              <span className="text-xs text-muted">· {d.assigned_to}</span>
            )}
            {d.status === "open" && (
              <Button
                variant="ghost"
                className="ml-auto !px-3 !py-1 text-xs"
                disabled={busy}
                onClick={() => act("claim")}
              >
                Take it
              </Button>
            )}
          </div>
          <p className="whitespace-pre-wrap font-display text-[15px] font-semibold text-fg">
            {d.subject}
          </p>
        </div>

        <Section
          title="What the AI saw and said"
          icon={<Bot className="h-3.5 w-3.5" />}
        >
          <Context d={d} />
        </Section>

        <Section title="Student" icon={<CircleUser className="h-3.5 w-3.5" />}>
          <Student s={d.student_context} />
        </Section>

        <Section
          title="Similar resolved tickets"
          icon={<History className="h-3.5 w-3.5" />}
        >
          {!d.similar.available ? (
            <p className="text-sm text-muted">
              Couldn&apos;t compare right now (embedding unavailable).
            </p>
          ) : d.similar.tickets.length === 0 ? (
            <p className="text-sm text-muted">None yet.</p>
          ) : (
            <div className="space-y-2">
              {d.similar.tickets.map((t) => (
                <div
                  key={t.id}
                  className="rounded-xl border border-line p-2.5 text-sm"
                >
                  <p className="text-fg">
                    #{t.id} {t.subject}{" "}
                    <span className="font-mono text-xs text-faint">
                      {t.similarity.toFixed(2)}
                    </span>
                  </p>
                  <p className="mt-1 line-clamp-3 text-xs text-muted">
                    {t.resolution}
                  </p>
                  {!resolved && (
                    <button
                      className="mt-1 text-xs text-brand-ink hover:underline"
                      onClick={() => setAnswer(t.resolution)}
                    >
                      Use this answer
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section
          title={resolved ? "Answer sent" : "Answer"}
          icon={<Send className="h-3.5 w-3.5" />}
        >
          {resolved ? (
            <div className="space-y-1">
              <p className="whitespace-pre-wrap rounded-xl bg-ok-soft/40 p-3 text-sm text-fg">
                {d.resolution}
              </p>
              {d.saved_to_kb && (
                <p className="flex items-center gap-1.5 text-xs text-ok">
                  <ShieldCheck className="h-3.5 w-3.5" /> In the knowledge base:
                  the AI uses it for this question now.
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {d.draft && (
                <p className="text-xs text-muted">
                  Starts from the AI&apos;s draft. Edit it before sending.
                </p>
              )}
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={6}
                placeholder="The answer the student will see"
                className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg"
              />
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <label
                  className={`flex items-center gap-2 ${d.kb_allowed ? "text-fg" : "text-faint"}`}
                >
                  <input
                    type="checkbox"
                    checked={toKb}
                    disabled={!d.kb_allowed}
                    onChange={(e) => setToKb(e.target.checked)}
                  />
                  Save to knowledge base
                </label>
                <select
                  aria-label="Course"
                  className={select}
                  value={d.course_id ?? ""}
                  disabled={!d.kb_allowed || busy}
                  onChange={(e) =>
                    act("course", {
                      course_id: e.target.value ? Number(e.target.value) : null,
                    })
                  }
                >
                  <option value="">No course</option>
                  {courses.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.code}
                    </option>
                  ))}
                </select>
                <Button
                  className="ml-auto"
                  disabled={busy || !answer.trim()}
                  onClick={() =>
                    act("resolve", { resolution: answer, save_to_kb: toKb })
                  }
                >
                  <BookCheck className="h-4 w-4" /> Resolve
                </Button>
              </div>
              <p className="text-xs text-faint">
                {d.kb_allowed
                  ? "Untick for a private or one-off answer. A saved answer is used by the AI the next time anyone in this course asks the same thing."
                  : "Account problems are about one person, so they never go into the knowledge base."}
              </p>
            </div>
          )}
        </Section>
        {error && <Alert title={error.message} detail={error.detail} />}
      </div>
    </Card>
  );
}

function Queue() {
  const [status, setStatus] = useState("open");
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState("");
  const [data, setData] = useState<Queue | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);

  const load = useCallback(async () => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    if (reason) q.set("reason", reason);
    if (category) q.set("category", category);
    try {
      setData(await apiFetch<Queue>(`/tickets?${q}`));
    } catch (e) {
      setError(err(e));
    }
  }, [status, reason, category]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    apiFetch<Course[]>("/chat/scope")
      .then(setCourses)
      .catch(() => setCourses([]));
    const id = new URLSearchParams(window.location.search).get("id");
    if (id) setSelected(Number(id));
  }, []);

  function pick(id: number) {
    setSelected(id);
    window.history.replaceState(null, "", `?id=${id}`);
  }

  if (error) return <Alert title={error.message} detail={error.detail} />;
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card
        title="Ticket queue"
        subtitle="Oldest first"
        icon={<Inbox className="h-4 w-4" />}
      >
        <div className="mb-3 flex flex-wrap gap-1.5">
          {["open", "in_progress", "resolved", ""].map((s) => (
            <button
              key={s || "all"}
              onClick={() => setStatus(s)}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${
                status === s
                  ? "border-brand bg-brand-soft text-brand-ink"
                  : "border-line text-muted hover:text-fg"
              }`}
            >
              {s ? STATUS_LABEL[s] : "All"}
              {s && data ? ` ${data.counts[s] ?? 0}` : ""}
            </button>
          ))}
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          <Search className="h-3.5 w-3.5" />
          <select
            aria-label="Reason"
            className={select}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          >
            <option value="">Any reason</option>
            {Object.entries(REASON_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select
            aria-label="Category"
            className={select}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">Any kind</option>
            <option value="academic">Course question</option>
            <option value="login">Login</option>
            <option value="payment">Payment</option>
          </select>
        </div>
        {!data ? (
          <SkeletonCard lines={5} />
        ) : data.tickets.length === 0 ? (
          <EmptyState
            title="Nothing here"
            hint="Tickets appear when the chat can't answer, isn't sure, or gets a 👎."
          />
        ) : (
          <div className="-mx-2 space-y-1">
            {data.tickets.map((t) => (
              <button
                key={t.id}
                onClick={() => pick(t.id)}
                className={`w-full rounded-xl px-2 py-2 text-left transition-colors ${
                  selected === t.id ? "bg-brand-soft" : "hover:bg-surface-2"
                }`}
              >
                <p className="line-clamp-2 text-sm text-fg">{t.subject}</p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-[11px] text-faint">
                    #{t.id}
                  </span>
                  <Tag>{REASON_LABEL[t.reason] ?? t.reason}</Tag>
                  {t.course_code && <Tag>{t.course_code}</Tag>}
                  <span className="text-[11px] text-faint">
                    {t.student} · {ago(t.created_at)}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
      {selected ? (
        <TicketPanel id={selected} courses={courses} onChanged={load} />
      ) : (
        <Card>
          <EmptyState
            title="Pick a ticket"
            hint="You'll see the question, what the AI found and said, and the student."
          />
        </Card>
      )}
    </div>
  );
}

export function TicketQueue({ role }: { role: Role }) {
  return (
    <PortalShell role={role} title="Tickets" showRoadmap={false}>
      {() => <Queue />}
    </PortalShell>
  );
}
