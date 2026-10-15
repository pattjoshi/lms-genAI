"use client";

// "I don't understand X" -> the concepts to study first, in order, each linked to its material.
// Only concepts a teacher approved are shown.

import { BookOpen, MessageCircleQuestion, Route, Search } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { Alert, Button, Card, Chip, EmptyState, SkeletonCard } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";

type Match = { uid: string; name: string; definition: string | null; course_code: string | null; score: number };
type Where = {
  file_name: string;
  course_code: string | null;
  module_title: string | null;
  pages: number[];
  section: string | null;
};
type Step = {
  uid: string;
  name: string;
  definition: string | null;
  status: string;
  is_target: boolean;
  needs: string[];
  materials: Where[];
  elsewhere: Where[];
  known: boolean;
  quiz_avg: number | null;
};
type Path = { target: { uid: string; name: string; course_code: string | null }; steps: Step[] };

function place(w: Where) {
  const at = w.pages.length ? `page ${w.pages.join(", ")}` : w.section;
  return `${w.file_name}${at ? ` · ${at}` : ""}`;
}

function StepCard({ step, n }: { step: Step; n: number }) {
  const ask = `/student/ask?q=${encodeURIComponent(`Explain ${step.name} with an example`)}`;
  return (
    <li className="relative pl-10">
      <span
        className={`absolute left-0 top-3 flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
          step.is_target ? "bg-brand text-brand-fg" : "bg-brand-soft text-brand-ink"
        }`}
      >
        {n}
      </span>
      <div
        className={`rounded-xl border p-3 ${step.is_target ? "border-brand" : "border-line"} ${step.known ? "opacity-70" : ""}`}
      >
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium text-fg">{step.name}</span>
          {step.is_target && <Chip>your question</Chip>}
          {step.status === "draft" && <Chip>draft</Chip>}
          {step.known && (
            <span className="rounded-full bg-ok-soft px-2 py-0.5 text-xs font-medium text-ok">
              you know this · quiz {step.quiz_avg}%
            </span>
          )}
          <Link href={ask} className="ml-auto inline-flex items-center gap-1 text-xs text-brand-ink hover:underline">
            <MessageCircleQuestion className="h-3.5 w-3.5" /> Ask about it
          </Link>
        </div>
        {step.definition && <p className="mt-1 text-sm text-muted">{step.definition}</p>}
        {step.needs.length > 0 && <p className="mt-1 text-xs text-faint">Builds on: {step.needs.join(", ")}</p>}
        <div className="mt-2 space-y-1 text-xs">
          {step.materials.map((m) => (
            <p key={m.file_name} className="flex items-center gap-1.5 text-muted">
              <BookOpen className="h-3.5 w-3.5 shrink-0" />
              Read: {m.module_title && <span className="text-fg">{m.module_title}</span>} {place(m)}
            </p>
          ))}
          {step.materials.length === 0 && step.elsewhere.length > 0 && (
            <p className="text-muted">
              Not explained in this course. Covered in{" "}
              {step.elsewhere.map((m) => `${m.course_code} (${place(m)})`).join(", ")}.
            </p>
          )}
          {step.materials.length === 0 && step.elsewhere.length === 0 && (
            <p className="text-faint">Background knowledge this course assumes. Ask the assistant or your teacher.</p>
          )}
        </div>
      </div>
    </li>
  );
}

function LearningPath() {
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [how, setHow] = useState<string | null>(null);
  const [path, setPath] = useState<Path | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const open = useCallback(async (uid: string) => {
    setBusy(true);
    setError(null);
    try {
      setPath(await apiFetch<Path>(`/learning-path?concept=${encodeURIComponent(uid)}`));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    } finally {
      setBusy(false);
    }
  }, []);

  const search = useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      setBusy(true);
      setError(null);
      setPath(null);
      try {
        const res = await apiFetch<{ matches: Match[]; how: string | null }>(
          `/learning-path/search?q=${encodeURIComponent(text)}`,
        );
        setMatches(res.matches);
        setHow(res.how);
        // A clear match goes straight to the path; otherwise the student picks.
        if (res.matches.length > 0 && (res.matches[0].score === 1 || res.matches.length === 1)) {
          await open(res.matches[0].uid);
        }
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
      } finally {
        setBusy(false);
      }
    },
    [open],
  );

  // /student/path?q=Backpropagation (links from the dashboard)
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("q");
    if (initial) {
      setQ(initial);
      search(initial);
    }
  }, [search]);

  return (
    <>
      <Card
        title="What don't you understand?"
        subtitle="Name a concept. You get what to study first, in order, with the file and page for each step."
        icon={<Route className="h-4 w-4" />}
      >
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            search(q);
          }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. backpropagation, joins, recursion"
            className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg focus:border-brand focus:outline-none"
          />
          <Button type="submit" disabled={busy || !q.trim()}>
            <Search className="h-4 w-4" /> Find
          </Button>
        </form>
        {error && (
          <div className="mt-3">
            <Alert title={error.message} detail={error.detail} />
          </div>
        )}
        {matches && matches.length === 0 && (
          <div className="mt-3">
            <EmptyState
              title="No published concept matches that"
              hint="Try another name, or ask the assistant. Your teacher may not have published this course's concepts yet."
            />
          </div>
        )}
        {matches && matches.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-muted">
            {how === "meaning" ? "Closest by meaning:" : "Matches:"}
            {matches.map((m) => (
              <button
                key={m.uid}
                onClick={() => open(m.uid)}
                className={`rounded-full px-2 py-0.5 font-medium ${
                  path?.target.uid === m.uid ? "bg-brand text-brand-fg" : "bg-brand-soft text-brand-ink hover:underline"
                }`}
              >
                {m.name} <span className="font-mono opacity-70">{m.course_code}</span>
              </button>
            ))}
          </div>
        )}
      </Card>

      {busy && !path && <SkeletonCard lines={4} />}
      {path && (
        <Card
          title={`Learning path: ${path.target.name}`}
          subtitle={`${path.steps.length} step${path.steps.length === 1 ? "" : "s"} · ${path.target.course_code} · prerequisites first`}
          icon={<Route className="h-4 w-4" />}
        >
          <ol className="space-y-3">
            {path.steps.map((s, i) => (
              <StepCard key={s.uid} step={s} n={i + 1} />
            ))}
          </ol>
        </Card>
      )}
    </>
  );
}

export default function LearningPathPage() {
  return (
    <PortalShell role="student" title="Learning path" showRoadmap={false}>
      {() => <LearningPath />}
    </PortalShell>
  );
}
