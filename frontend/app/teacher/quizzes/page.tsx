"use client";

// Quizzes: the AI drafts multiple-choice questions from a file or topic. The teacher checks each one
// against the passage it came from, fixes or rejects it, and publishes. Students only see published quizzes.

import { BookOpen, Check, ListChecks, Pencil, Send, Sparkles, Trash2, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { Alert, Button, Card, Chip, EmptyState, SkeletonCard } from "@/components/ui";
import { useApi } from "@/components/useApi";
import { apiFetch, ApiError } from "@/lib/api";

type Option = { id: number; code: string; title: string };
type Sources = {
  files: { id: number; file_name: string; module_title: string }[];
  topics: { id: number; name: string; module_title: string }[];
};
type Counts = { draft?: number; approved?: number; rejected?: number };
type Quiz = {
  id: number;
  title: string;
  status: "draft" | "published";
  source_label: string | null;
  generation_cost_usd: number;
  questions?: Counts;
  attempts?: number;
};
type Source = {
  file_name: string | null;
  page: number | null;
  section: string | null;
  text: string | null;
  quote: string | null;
};
type Question = {
  id: number;
  position: number;
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
  difficulty: string;
  status: "draft" | "approved" | "rejected";
  edited: boolean;
  source: Source;
};

const LETTERS = ["A", "B", "C", "D"];
const STATUS_STYLE: Record<string, string> = {
  draft: "bg-surface-2 text-muted",
  approved: "bg-ok-soft text-ok",
  rejected: "bg-bad-soft text-bad",
  published: "bg-ok-soft text-ok",
};
const input =
  "w-full rounded-lg border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-brand focus:outline-none";
const select = "rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg";

function toError(e: unknown) {
  return e instanceof ApiError ? e : new ApiError(0, "unknown", String(e));
}

/** The passage with the quote that proves the answer highlighted. */
function SourcePassage({ source }: { source: Source }) {
  const text = source.text ?? "";
  const quote = source.quote ?? "";
  const at = quote ? text.toLowerCase().indexOf(quote.toLowerCase()) : -1;
  const where = [source.file_name, source.page ? `page ${source.page}` : source.section].filter(Boolean).join(" · ");
  return (
    <details className="mt-2 rounded-lg bg-surface-2/60 p-2 text-xs text-muted">
      <summary className="cursor-pointer">
        <BookOpen className="mr-1 inline h-3.5 w-3.5" />
        Source: {where} <span className="text-faint">· “{quote}”</span>
      </summary>
      <p className="mt-2 whitespace-pre-wrap leading-relaxed">
        {at < 0 ? (
          text
        ) : (
          <>
            {text.slice(0, at)}
            <mark className="rounded bg-warn-soft px-0.5 text-fg">{text.slice(at, at + quote.length)}</mark>
            {text.slice(at + quote.length)}
          </>
        )}
      </p>
    </details>
  );
}

function QuestionCard({ q, act }: { q: Question; act: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [question, setQuestion] = useState(q.question);
  const [options, setOptions] = useState(q.options);
  const [correct, setCorrect] = useState(q.correct_index);
  const [explanation, setExplanation] = useState(q.explanation);

  const patch = (body: object) =>
    act(() => apiFetch(`/quizzes/questions/${q.id}`, { method: "PATCH", body: JSON.stringify(body) }));

  return (
    <div className={`rounded-xl border border-line p-3 ${q.status === "rejected" ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-start gap-1.5">
        <span className="mt-0.5 text-xs font-semibold text-faint">Q{q.position}</span>
        {editing ? (
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} className={`${input} flex-1`} />
        ) : (
          <span className="flex-1 font-medium text-fg">{q.question}</span>
        )}
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[q.status]}`}>{q.status}</span>
        <Chip>{q.difficulty}</Chip>
        {q.edited && <Chip>edited</Chip>}
      </div>

      <ul className="mt-2 space-y-1 text-sm">
        {(editing ? options : q.options).map((o, i) => {
          const right = (editing ? correct : q.correct_index) === i;
          return (
            <li key={i} className={`flex items-center gap-2 rounded-lg px-2 py-1 ${right ? "bg-ok-soft" : ""}`}>
              {editing ? (
                <>
                  <input type="radio" checked={right} onChange={() => setCorrect(i)} title="Correct answer" />
                  <input
                    value={o}
                    onChange={(e) => setOptions(options.map((x, j) => (j === i ? e.target.value : x)))}
                    className={input}
                  />
                </>
              ) : (
                <>
                  <span className={`w-4 text-xs font-semibold ${right ? "text-ok" : "text-faint"}`}>{LETTERS[i]}</span>
                  <span className={right ? "text-ok" : "text-fg"}>{o}</span>
                  {right && <Check className="h-3.5 w-3.5 text-ok" />}
                </>
              )}
            </li>
          );
        })}
      </ul>

      {editing ? (
        <textarea
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
          rows={2}
          className={`${input} mt-2`}
        />
      ) : (
        <p className="mt-2 text-xs text-muted">Why: {q.explanation}</p>
      )}

      <SourcePassage source={q.source} />

      <div className="mt-2 flex flex-wrap gap-1.5">
        {editing ? (
          <>
            <Button
              onClick={async () => {
                await patch({ question, options, correct_index: correct, explanation });
                setEditing(false);
              }}
            >
              Save
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <>
            {q.status !== "approved" && (
              <Button variant="ghost" onClick={() => patch({ status: "approved" })} className="text-ok">
                <Check className="h-4 w-4" /> Approve
              </Button>
            )}
            {q.status !== "rejected" && (
              <Button variant="ghost" onClick={() => patch({ status: "rejected" })} className="text-bad">
                <X className="h-4 w-4" /> Reject
              </Button>
            )}
            {q.status !== "draft" && (
              <Button variant="ghost" onClick={() => patch({ status: "draft" })}>
                <Undo2 className="h-4 w-4" /> Undo
              </Button>
            )}
            <Button variant="ghost" onClick={() => setEditing(true)}>
              <Pencil className="h-4 w-4" /> Edit
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

function QuizEditor({ quizId, onChange, onClose }: { quizId: number; onChange: () => void; onClose: () => void }) {
  const [data, setData] = useState<{ quiz: Quiz; questions: Question[] } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [title, setTitle] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await apiFetch<{ quiz: Quiz; questions: Question[] }>(`/quizzes/${quizId}/manage`);
      setData(d);
      setTitle(d.quiz.title);
    } catch (e) {
      setError(toError(e));
    }
  }, [quizId]);

  useEffect(() => {
    load();
  }, [load]);

  const act = useCallback(
    async (fn: () => Promise<unknown>) => {
      try {
        setError(null);
        await fn();
        await load();
        onChange();
      } catch (e) {
        setError(toError(e));
      }
    },
    [load, onChange],
  );

  if (!data) return error ? <Alert title={error.message} /> : <SkeletonCard lines={5} />;
  const { quiz, questions } = data;
  const drafts = questions.filter((q) => q.status === "draft").length;
  const approved = questions.filter((q) => q.status === "approved").length;
  const setStatus = (status: string) =>
    act(() => apiFetch(`/quizzes/${quiz.id}`, { method: "PATCH", body: JSON.stringify({ status }) }));

  return (
    <Card
      title={quiz.title}
      subtitle={`${quiz.source_label ?? ""} · ${approved} approved, ${drafts} to review · cost $${quiz.generation_cost_usd.toFixed(4)}`}
      icon={<ListChecks className="h-4 w-4" />}
      action={
        <div className="flex gap-2">
          {quiz.status === "draft" ? (
            <Button
              onClick={() => setStatus("published")}
              disabled={drafts > 0 || approved === 0}
              title={drafts > 0 ? "Review every question first" : undefined}
            >
              <Send className="h-4 w-4" /> Publish
            </Button>
          ) : (
            <Button variant="ghost" onClick={() => setStatus("draft")}>
              Unpublish
            </Button>
          )}
          <Button
            variant="ghost"
            title="Delete quiz"
            onClick={() => {
              if (!confirm(`Delete "${quiz.title}"?`)) return;
              apiFetch(`/quizzes/${quiz.id}`, { method: "DELETE" }).then(
                () => {
                  onChange();
                  onClose();
                },
                (e) => setError(toError(e)),
              );
            }}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      }
    >
      <div className="mb-3 flex gap-2">
        <input value={title} onChange={(e) => setTitle(e.target.value)} className={input} />
        {title !== quiz.title && (
          <Button
            variant="ghost"
            onClick={() =>
              act(() => apiFetch(`/quizzes/${quiz.id}`, { method: "PATCH", body: JSON.stringify({ title }) }))
            }
          >
            Rename
          </Button>
        )}
      </div>
      {error && (
        <div className="mb-3">
          <Alert title={error.message} detail={error.detail} />
        </div>
      )}
      {quiz.status === "draft" && drafts > 0 && (
        <p className="mb-3 text-xs text-muted">
          Check each answer against its source passage. Approve or reject every question, then publish. Students only
          get approved questions.
        </p>
      )}
      <div className="space-y-3">
        {questions.map((q) => (
          <QuestionCard key={`${q.id}-${q.status}-${q.question}-${q.correct_index}-${q.options.join("|")}`} q={q} act={act} />
        ))}
      </div>
    </Card>
  );
}

function Quizzes() {
  const options = useApi<Option[]>("/documents/options");
  const [courseId, setCourseId] = useState<number | null>(null);
  const [sources, setSources] = useState<Sources | null>(null);
  const [quizzes, setQuizzes] = useState<Quiz[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [kind, setKind] = useState<"file" | "topic">("file");
  const [sourceId, setSourceId] = useState("");
  const [count, setCount] = useState(5);
  const [busy, setBusy] = useState(false);
  const [dropped, setDropped] = useState<string[]>([]);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (courseId === null && options.data?.length) setCourseId(options.data[0].id);
  }, [options.data, courseId]);

  const loadList = useCallback(async () => {
    if (courseId === null) return;
    try {
      setQuizzes(await apiFetch<Quiz[]>(`/quizzes/manage?course_id=${courseId}`));
    } catch (e) {
      setError(toError(e));
    }
  }, [courseId]);

  useEffect(() => {
    if (courseId === null) return;
    setQuizzes(null);
    setOpen(null);
    setSourceId("");
    apiFetch<Sources>(`/quizzes/sources?course_id=${courseId}`).then(setSources, (e) => setError(toError(e)));
    loadList();
  }, [courseId, loadList]);

  async function generate() {
    setBusy(true);
    setError(null);
    setDropped([]);
    try {
      const body = { course_id: courseId, num_questions: count, [kind === "file" ? "document_id" : "topic_id"]: Number(sourceId) };
      const res = await apiFetch<{ quiz: Quiz; dropped: string[] }>("/quizzes/generate", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setDropped(res.dropped);
      await loadList();
      setOpen(res.quiz.id);
    } catch (e) {
      setError(toError(e));
    } finally {
      setBusy(false);
    }
  }

  const list = kind === "file" ? sources?.files : sources?.topics;

  return (
    <>
      <Card
        title="Generate a quiz"
        subtitle="The AI writes multiple-choice questions from your material. Each one keeps the passage it came from, so you can check it in a glance."
        icon={<Sparkles className="h-4 w-4" />}
      >
        <div className="flex flex-wrap items-center gap-2">
          <select value={courseId ?? ""} onChange={(e) => setCourseId(Number(e.target.value))} className={select}>
            {options.data?.map((o) => (
              <option key={o.id} value={o.id}>
                {o.code} · {o.title}
              </option>
            ))}
          </select>
          <div className="flex rounded-xl border border-line p-0.5">
            {(["file", "topic"] as const).map((k) => (
              <button
                key={k}
                onClick={() => {
                  setKind(k);
                  setSourceId("");
                }}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium ${kind === k ? "bg-brand text-brand-fg" : "text-muted"}`}
              >
                From a {k}
              </button>
            ))}
          </div>
          <select value={sourceId} onChange={(e) => setSourceId(e.target.value)} className={`${select} min-w-56`}>
            <option value="">{kind === "file" ? "Pick a file…" : "Pick a topic…"}</option>
            {list?.map((s) => (
              <option key={s.id} value={s.id}>
                {"file_name" in s ? s.file_name : s.name} ({s.module_title})
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5 text-sm text-muted">
            Questions
            <input
              type="number"
              min={1}
              max={10}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className={`${input} w-16`}
            />
          </label>
          <Button onClick={generate} disabled={busy || !sourceId}>
            <Sparkles className="h-4 w-4" /> {busy ? "Writing questions…" : "Generate"}
          </Button>
        </div>
        {sources && sources.files.length === 0 && (
          <p className="mt-3 text-xs text-faint">No ready files in this course yet. Upload some in Course files.</p>
        )}
        {dropped.length > 0 && (
          <div className="mt-3">
            <Alert
              tone="warn"
              title={`${dropped.length} AI question(s) failed the checks and were left out`}
              detail={dropped.join(" · ")}
            />
          </div>
        )}
        {(error || options.error) && (
          <div className="mt-3">
            <Alert title={(error ?? options.error)!.message} detail={(error ?? options.error)!.detail} />
          </div>
        )}
      </Card>

      <Card title="Quizzes in this course" icon={<ListChecks className="h-4 w-4" />}>
        {!quizzes && <SkeletonCard lines={2} />}
        {quizzes?.length === 0 && <EmptyState title="No quizzes yet" hint="Generate one above." />}
        <div className="space-y-1.5">
          {quizzes?.map((q) => (
            <button
              key={q.id}
              onClick={() => setOpen(open === q.id ? null : q.id)}
              className={`flex w-full flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm ${
                open === q.id ? "border-brand" : "border-line hover:bg-surface-2"
              }`}
            >
              <span className="font-medium text-fg">{q.title}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[q.status]}`}>{q.status}</span>
              <span className="text-xs text-faint">{q.source_label}</span>
              <span className="ml-auto text-xs text-muted">
                {q.questions?.approved ?? 0} approved · {q.questions?.draft ?? 0} to review · {q.attempts ?? 0} attempts
              </span>
            </button>
          ))}
        </div>
      </Card>

      {open !== null && <QuizEditor key={open} quizId={open} onChange={loadList} onClose={() => setOpen(null)} />}
    </>
  );
}

export default function QuizzesPage() {
  return (
    <PortalShell role="teacher" title="Quizzes" showRoadmap={false}>
      {() => <Quizzes />}
    </PortalShell>
  );
}
