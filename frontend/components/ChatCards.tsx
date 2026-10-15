"use client";

// Phase 4: the chat routes each message (course question, learning path, practice, progress, support).
// These are the cards the agent sends next to its text answer, plus the "how it was routed" line.

import { BookOpen, Check, CircleCheck, Dumbbell, Route as RouteIcon, Signpost, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Chip } from "@/components/ui";
import { apiFetch } from "@/lib/api";

export type RouteInfo = {
  intent: string;
  method: "rules" | "embedding" | "llm" | "default";
  confidence: number;
  topic: string | null;
  detail: { rule?: string; scores?: Record<string, number>; note?: string; error?: string };
  fallback?: string;
};

type Where = { file_name: string; course_code: string | null; module_title: string | null; pages: number[]; section: string | null };
type Step = {
  uid: string;
  name: string;
  definition: string | null;
  is_target: boolean;
  known: boolean;
  quiz_avg: number | null;
  materials: Where[];
  elsewhere: Where[];
};
type PathData = { target: { uid: string; name: string; course_code: string | null }; steps: Step[] };
type Match = { uid: string; name: string; course_code: string | null; score: number };
type Result = {
  chosen: number;
  correct: boolean;
  correct_index: number;
  explanation: string;
  source: { file_name: string; page: number | null; section: string | null };
};
type PracticeQuestion = { index: number; question: string; options: string[]; difficulty: string; result?: Result };
type Practice = { id: number; topic: string; course_code: string | null; questions: PracticeQuestion[] };
type Weak = { name: string; course_code: string | null; why: string };

export type CardData =
  | { kind: "path"; path: PathData }
  | { kind: "choose_concept"; topic: string; matches: Match[] }
  | { kind: "practice"; practice: Practice }
  | { kind: "progress"; weak: Weak[] }
  | { kind: "support"; facts: Record<string, unknown> };

const INTENT_LABEL: Record<string, string> = {
  doubt: "Course question",
  learning_path: "Learning path",
  practice: "Practice",
  progress: "Your progress",
  support: "Account / payment help",
};
const METHOD_LABEL: Record<string, string> = {
  rules: "matched a rule",
  embedding: "closest examples",
  llm: "AI classifier",
  default: "default (router unsure)",
};
const LETTERS = ["A", "B", "C", "D"];

/** "Learning path · matched a rule": which part of the LMS answered, and how it was decided. */
export function RouteLine({ route }: { route: RouteInfo }) {
  const scores = route.detail.scores;
  const title = route.detail.rule
    ? `Rule: ${route.detail.rule}`
    : scores
      ? Object.entries(scores)
          .map(([k, v]) => `${k} ${v.toFixed(2)}`)
          .join(" · ")
      : undefined;
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[11px] text-faint">
      <Signpost className="h-3 w-3" />
      <span className="font-medium text-muted">{INTENT_LABEL[route.intent] ?? route.intent}</span>
      <span title={title}>
        · {METHOD_LABEL[route.method] ?? route.method}
        {route.method === "embedding" && ` (${route.confidence.toFixed(2)})`}
      </span>
      {route.topic && <span>· topic “{route.topic}”</span>}
      {route.fallback && <span className="text-warn">· {route.fallback}</span>}
    </div>
  );
}

function place(w: Where) {
  const at = w.pages.length ? `p. ${w.pages.join(", ")}` : w.section;
  return `${w.file_name}${at ? ` · ${at}` : ""}`;
}

function PathCard({ path }: { path: PathData }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <ol className="space-y-1.5 text-sm">
        {path.steps.map((s, i) => (
          <li key={s.uid} className={`flex flex-wrap items-baseline gap-x-2 ${s.known ? "opacity-60" : ""}`}>
            <span className="w-5 text-xs font-semibold text-faint">{i + 1}.</span>
            <span className={`font-medium ${s.is_target ? "text-brand-ink" : "text-fg"}`}>{s.name}</span>
            {s.known && (
              <span className="inline-flex items-center gap-1 text-xs text-ok">
                <CircleCheck className="h-3 w-3" /> you know this (quiz {s.quiz_avg}%)
              </span>
            )}
            <span className="text-xs text-muted">
              {s.materials[0]
                ? place(s.materials[0])
                : s.elsewhere[0]
                  ? `in ${s.elsewhere[0].course_code}: ${place(s.elsewhere[0])}`
                  : "background knowledge"}
            </span>
          </li>
        ))}
      </ol>
      <Link
        href={`/student/path?q=${encodeURIComponent(path.target.name)}`}
        className="mt-2 inline-flex items-center gap-1 text-xs text-brand-ink hover:underline"
      >
        <RouteIcon className="h-3.5 w-3.5" /> Open the full learning path
      </Link>
    </div>
  );
}

function PracticeCard({ practice }: { practice: Practice }) {
  const [results, setResults] = useState<Record<number, Result>>(() =>
    Object.fromEntries(practice.questions.filter((q) => q.result).map((q) => [q.index, q.result!])),
  );
  const [error, setError] = useState<string | null>(null);

  async function pick(index: number, chosen: number) {
    if (results[index]) return;
    try {
      const r = await apiFetch<Result>(`/practice/${practice.id}/answers`, {
        method: "POST",
        body: JSON.stringify({ index, chosen }),
      });
      setResults((all) => ({ ...all, [index]: r }));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  const done = Object.values(results);
  return (
    <div className="space-y-3 rounded-xl border border-line p-3">
      <p className="flex items-center gap-1.5 text-xs text-muted">
        <Dumbbell className="h-3.5 w-3.5" /> Practice · {practice.topic} · {practice.course_code}
        {done.length === practice.questions.length && (
          <span className="ml-auto font-medium text-fg">
            {done.filter((r) => r.correct).length} / {done.length} right
          </span>
        )}
      </p>
      {practice.questions.map((q) => {
        const r = results[q.index];
        return (
          <div key={q.index}>
            <p className="text-sm font-medium text-fg">
              {q.index + 1}. {q.question}
            </p>
            <div className="mt-1.5 grid gap-1 sm:grid-cols-2">
              {q.options.map((o, i) => {
                const tone = !r
                  ? "border-line hover:border-brand/50 hover:bg-surface-2"
                  : i === r.correct_index
                    ? "border-ok/40 bg-ok-soft"
                    : i === r.chosen
                      ? "border-bad/40 bg-bad-soft"
                      : "border-line opacity-60";
                return (
                  <button
                    key={i}
                    disabled={!!r}
                    onClick={() => pick(q.index, i)}
                    className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-sm text-fg ${tone}`}
                  >
                    <span className="text-xs font-semibold text-faint">{LETTERS[i]}</span>
                    <span className="flex-1">{o}</span>
                    {r && i === r.correct_index && <Check className="h-3.5 w-3.5 text-ok" />}
                    {r && i === r.chosen && !r.correct && <X className="h-3.5 w-3.5 text-bad" />}
                  </button>
                );
              })}
            </div>
            {r && (
              <p className="mt-1.5 text-xs text-muted">
                <span className={r.correct ? "font-medium text-ok" : "font-medium text-bad"}>
                  {r.correct ? "Right. " : "Not quite. "}
                </span>
                {r.explanation}{" "}
                <span className="inline-flex items-center gap-1 text-faint">
                  <BookOpen className="h-3 w-3" /> {r.source.file_name}
                  {r.source.page ? ` · page ${r.source.page}` : r.source.section ? ` · ${r.source.section}` : ""}
                </span>
              </p>
            )}
          </div>
        );
      })}
      {error && <p className="text-xs text-bad">{error}</p>}
      <p className="text-[11px] text-faint">
        Written by the AI from your course material and checked against it, not reviewed by your teacher. Practice
        only: it doesn&apos;t count as a score.
      </p>
    </div>
  );
}

function ProgressCard({ weak, onAsk }: { weak: Weak[]; onAsk: (q: string) => void }) {
  if (!weak.length) return null;
  return (
    <div className="divide-y divide-line rounded-xl border border-line">
      {weak.map((w) => (
        <div key={w.name} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
          <span className="font-medium text-fg">{w.name}</span>
          {w.course_code && <Chip mono>{w.course_code}</Chip>}
          <span className="text-xs text-faint">{w.why}</span>
          <span className="ml-auto flex gap-3 text-xs">
            <Link href={`/student/path?q=${encodeURIComponent(w.name)}`} className="text-brand-ink hover:underline">
              study path
            </Link>
            <button onClick={() => onAsk(`Quiz me on ${w.name}`)} className="text-brand-ink hover:underline">
              practise
            </button>
          </span>
        </div>
      ))}
    </div>
  );
}

export function ChatCard({ card, onAsk }: { card: CardData; onAsk: (q: string) => void }) {
  switch (card.kind) {
    case "path":
      return <PathCard path={card.path} />;
    case "practice":
      return <PracticeCard practice={card.practice} />;
    case "progress":
      return <ProgressCard weak={card.weak} onAsk={onAsk} />;
    case "choose_concept":
      return (
        <div className="flex flex-wrap gap-1.5">
          {card.matches.map((m) => (
            <button
              key={m.uid}
              onClick={() => onAsk(`I don't understand ${m.name}`)}
              className="rounded-full bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand-ink hover:underline"
            >
              {m.name} <span className="font-mono opacity-70">{m.course_code}</span>
            </button>
          ))}
        </div>
      );
    default:
      return null; // support: the text says it all
  }
}
