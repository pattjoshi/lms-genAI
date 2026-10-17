"use client";

import { BookOpenCheck, Building2, GraduationCap, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useRef, useState, type KeyboardEvent } from "react";

type Audience = {
  id: string;
  label: string;
  icon: LucideIcon;
  title: string;
  text: string;
  points: string[];
  cta: { label: string; href: string };
};

const AUDIENCES: Audience[] = [
  {
    id: "learners",
    label: "Learners",
    icon: GraduationCap,
    title: "Stuck at 11 pm? Ask, and keep going.",
    text: "Your tutor answers from the course you're taking, shows the page it used, and notices which topics you keep getting wrong.",
    points: [
      "Answers with the source page, never made up",
      "\"I don't understand backprop\" turns into a step-by-step path",
      "Practice questions on your weak topics",
    ],
    cta: { label: "Start learning", href: "/signup" },
  },
  {
    id: "instructors",
    label: "Instructors",
    icon: BookOpenCheck,
    title: "Upload your notes. Your AI teaching assistant is ready.",
    text: "PDFs, slides and docs become a tutor that answers in your words. You approve what it says before students see it.",
    points: [
      "Concept maps and quizzes drafted from your files, approved by you",
      "See the most asked doubts, grouped by meaning",
      "Spot gaps: questions your material can't answer yet",
    ],
    cta: { label: "Teach with us", href: "/signup?plan=teams" },
  },
  {
    id: "teams",
    label: "Teams and colleges",
    icon: Building2,
    title: "One place to train everyone, with control over the AI.",
    text: "Roles decide who sees what, on every request. Cost, latency and answer quality are tracked, and off-topic or unsafe questions are refused.",
    points: [
      "Student, instructor, support and admin roles",
      "Usage, cost and quality dashboards",
      "Ask your learning data in plain English, safely",
    ],
    cta: { label: "Talk to us", href: "/signup?plan=teams" },
  },
];

export function AudienceTabs() {
  const [active, setActive] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  // Arrow keys move between tabs (WAI-ARIA tabs pattern).
  const onKey = (e: KeyboardEvent) => {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = (active + delta + AUDIENCES.length) % AUDIENCES.length;
    setActive(next);
    tabs.current[next]?.focus();
  };

  const a = AUDIENCES[active];
  return (
    <div>
      <div role="tablist" aria-label="Who it's for" onKeyDown={onKey} className="flex flex-wrap justify-center gap-2">
        {AUDIENCES.map((x, i) => {
          const Icon = x.icon;
          return (
            <button
              key={x.id}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              id={`tab-${x.id}`}
              role="tab"
              type="button"
              aria-selected={i === active}
              aria-controls={`panel-${x.id}`}
              tabIndex={i === active ? 0 : -1}
              onClick={() => setActive(i)}
              className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition-colors ${
                i === active
                  ? "border-transparent bg-fg text-bg"
                  : "border-line bg-surface text-muted hover:text-fg"
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {x.label}
            </button>
          );
        })}
      </div>

      <div
        id={`panel-${a.id}`}
        role="tabpanel"
        aria-labelledby={`tab-${a.id}`}
        className="mt-8 grid items-center gap-8 rounded-3xl border border-line bg-surface p-6 shadow-card sm:p-10 lg:grid-cols-2"
      >
        <div>
          <h3 className="font-display text-2xl font-bold text-fg sm:text-3xl">{a.title}</h3>
          <p className="mt-3 text-muted">{a.text}</p>
          <Link
            href={a.cta.href}
            className="mt-6 inline-flex rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-brand-fg hover:bg-brand-hover"
          >
            {a.cta.label}
          </Link>
        </div>
        <ul className="grid gap-3">
          {a.points.map((p, i) => (
            <li key={p} className="flex items-start gap-3 rounded-2xl border border-line bg-surface-2/60 p-4">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-soft font-mono text-xs font-bold text-brand-ink">
                {i + 1}
              </span>
              <span className="text-sm font-medium text-fg">{p}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
