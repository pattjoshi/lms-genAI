"use client";

// Quizzes your teachers published. Answers are checked on the server; after submitting you see
// why each answer is right and where in the course material to read about it.

import { BookOpen, Check, ListChecks, MessageCircleQuestion, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { Alert, Button, Card, Chip, EmptyState, ScoreText, SkeletonCard } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";

type QuizItem = {
  id: number;
  title: string;
  course_code: string | null;
  num_questions: number;
  attempts: number;
  best_score: number | null;
};
type Question = { id: number; position: number; question: string; options: string[]; difficulty: string };
type Source = { file_name: string | null; page: number | null; section: string | null; quote: string | null };
type Result = {
  question_id: number;
  chosen: number | null;
  correct: boolean;
  correct_index: number;
  explanation: string;
  source: Source;
};

const LETTERS = ["A", "B", "C", "D"];

function toError(e: unknown) {
  return e instanceof ApiError ? e : new ApiError(0, "unknown", String(e));
}

function TakeQuiz({ quiz, onDone }: { quiz: QuizItem; onDone: () => void }) {
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [result, setResult] = useState<{ score_pct: number; results: Result[] } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const started = useRef(Date.now());

  const load = useCallback(async () => {
    setResult(null);
    setAnswers({});
    started.current = Date.now();
    try {
      setQuestions((await apiFetch<{ questions: Question[] }>(`/quizzes/${quiz.id}`)).questions);
    } catch (e) {
      setError(toError(e));
    }
  }, [quiz.id]);

  useEffect(() => {
    load();
  }, [load]);

  async function submit() {
    setBusy(true);
    try {
      const res = await apiFetch<{ score_pct: number; results: Result[] }>(`/quizzes/${quiz.id}/attempts`, {
        method: "POST",
        body: JSON.stringify({ answers, time_taken_sec: Math.round((Date.now() - started.current) / 1000) }),
      });
      setResult(res);
      onDone();
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(toError(e));
    } finally {
      setBusy(false);
    }
  }

  if (error) return <Alert title={error.message} detail={error.detail} />;
  if (!questions) return <SkeletonCard lines={5} />;
  const byId = Object.fromEntries((result?.results ?? []).map((r) => [r.question_id, r]));
  const answered = Object.keys(answers).length;

  return (
    <Card
      title={quiz.title}
      subtitle={`${quiz.course_code} · ${questions.length} questions`}
      icon={<ListChecks className="h-4 w-4" />}
      action={
        result && (
          <div className="text-right">
            <ScoreText score={result.score_pct} />
            <p className="text-xs text-muted">
              {result.results.filter((r) => r.correct).length} of {result.results.length} right
            </p>
          </div>
        )
      }
    >
      <ol className="space-y-4">
        {questions.map((q) => {
          const r = byId[q.id];
          return (
            <li key={q.id} className="rounded-xl border border-line p-3">
              <p className="font-medium text-fg">
                {q.position}. {q.question}
              </p>
              <div className="mt-2 space-y-1">
                {q.options.map((o, i) => {
                  const chosen = (r ? r.chosen : answers[q.id]) === i;
                  const tone = !r
                    ? chosen
                      ? "border-brand bg-brand-soft"
                      : "border-line hover:bg-surface-2"
                    : i === r.correct_index
                      ? "border-ok/40 bg-ok-soft"
                      : chosen
                        ? "border-bad/40 bg-bad-soft"
                        : "border-line opacity-70";
                  return (
                    <button
                      key={i}
                      disabled={!!r}
                      onClick={() => setAnswers({ ...answers, [q.id]: i })}
                      className={`flex w-full items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-sm text-fg ${tone}`}
                    >
                      <span className="w-4 text-xs font-semibold text-faint">{LETTERS[i]}</span>
                      <span className="flex-1">{o}</span>
                      {r && i === r.correct_index && <Check className="h-4 w-4 text-ok" />}
                      {r && chosen && !r.correct && <X className="h-4 w-4 text-bad" />}
                    </button>
                  );
                })}
              </div>
              {r && (
                <div className="mt-2 space-y-1 text-xs text-muted">
                  {r.chosen === null && <Chip>skipped</Chip>}
                  <p>{r.explanation}</p>
                  <p className="flex flex-wrap items-center gap-1.5">
                    <BookOpen className="h-3.5 w-3.5" />
                    Read: {r.source.file_name}
                    {r.source.page ? ` · page ${r.source.page}` : r.source.section ? ` · ${r.source.section}` : ""}
                    {!r.correct && (
                      <Link
                        href={`/student/ask?q=${encodeURIComponent(`Explain: ${q.question}`)}`}
                        className="ml-auto inline-flex items-center gap-1 text-brand-ink hover:underline"
                      >
                        <MessageCircleQuestion className="h-3.5 w-3.5" /> Ask about it
                      </Link>
                    )}
                  </p>
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <div className="mt-4 flex items-center gap-3">
        {result ? (
          <Button variant="ghost" onClick={load}>
            <RotateCcw className="h-4 w-4" /> Try again
          </Button>
        ) : (
          <>
            <Button onClick={submit} disabled={busy || answered === 0}>
              Submit
            </Button>
            <span className="text-xs text-muted">
              {answered} of {questions.length} answered
              {answered > 0 && answered < questions.length && " · unanswered questions count as wrong"}
            </span>
          </>
        )}
      </div>
    </Card>
  );
}

function StudentQuizzes() {
  const [quizzes, setQuizzes] = useState<QuizItem[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [open, setOpen] = useState<QuizItem | null>(null);

  const load = useCallback(async () => {
    try {
      setQuizzes(await apiFetch<QuizItem[]>("/quizzes"));
    } catch (e) {
      setError(toError(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <Card
        title="Quizzes"
        subtitle="Published by your teachers. After you submit, each answer shows where in the course material to read about it."
        icon={<ListChecks className="h-4 w-4" />}
      >
        {error && <Alert title={error.message} detail={error.detail} />}
        {!quizzes && !error && <SkeletonCard lines={2} />}
        {quizzes?.length === 0 && (
          <EmptyState title="No quizzes yet" hint="Your teachers haven't published any quizzes for your courses." />
        )}
        <div className="space-y-1.5">
          {quizzes?.map((q) => (
            <button
              key={q.id}
              onClick={() => setOpen(open?.id === q.id ? null : q)}
              className={`flex w-full flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm ${
                open?.id === q.id ? "border-brand" : "border-line hover:bg-surface-2"
              }`}
            >
              <span className="font-medium text-fg">{q.title}</span>
              <Chip mono>{q.course_code}</Chip>
              <span className="text-xs text-muted">{q.num_questions} questions</span>
              <span className="ml-auto text-xs text-muted">
                {q.best_score === null ? (
                  "not taken yet"
                ) : (
                  <>
                    best <ScoreText score={q.best_score} /> · {q.attempts} attempt{q.attempts === 1 ? "" : "s"}
                  </>
                )}
              </span>
            </button>
          ))}
        </div>
      </Card>
      {open && <TakeQuiz key={open.id} quiz={open} onDone={load} />}
    </>
  );
}

export default function StudentQuizzesPage() {
  return (
    <PortalShell role="student" title="Quizzes" showRoadmap={false}>
      {() => <StudentQuizzes />}
    </PortalShell>
  );
}
