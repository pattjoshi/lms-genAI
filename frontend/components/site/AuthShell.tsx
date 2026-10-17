import { BadgeCheck, FileText, Route } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Logo } from "./Logo";

const POINTS = [
  { icon: FileText, text: "Answers from your own course material, with the page they came from" },
  { icon: Route, text: "Learning paths that skip what you already know" },
  { icon: BadgeCheck, text: "Quizzes your instructor approved, and a person when the AI isn't sure" },
];

/** Split layout for log in / sign up: the form on the left, why it's worth it on the right (desktop). */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_minmax(0,560px)] xl:grid-cols-[1fr_640px]">
      <div className="flex flex-col px-4 py-6 sm:px-8">
        <div className="flex items-center justify-between">
          <Logo />
          <ThemeToggle />
        </div>
        <main id="main" className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-10">
          {children}
        </main>
        <p className="text-center text-xs text-faint">
          <Link href="/" className="hover:text-fg">
            ← Back to the home page
          </Link>
        </p>
      </div>

      <aside
        aria-label="Why learners join"
        className="relative hidden overflow-hidden bg-gradient-to-br from-[#4338ca] via-[#6d5efc] to-[#0e7490] p-12 text-white lg:flex lg:flex-col lg:justify-between"
      >
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_80%_0%,rgba(255,255,255,0.22),transparent_45%)]" />
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.07)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.07)_1px,transparent_1px)] bg-[size:48px_48px]" />
        <p className="relative text-sm font-semibold uppercase tracking-wider text-white/80">LMS GenAI</p>
        <div className="relative">
          <h2 className="font-display text-4xl font-bold leading-tight">Every doubt answered, with the source to prove it.</h2>
          <ul className="mt-10 space-y-5">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/15 backdrop-blur">
                  <Icon className="h-4.5 w-4.5" aria-hidden />
                </span>
                <span className="pt-1.5 text-white/90">{text}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-sm text-white/70">Programming · AI and machine learning · Data · Computer science</p>
      </aside>
    </div>
  );
}

export function Divider({ label }: { label: string }) {
  return (
    <div className="my-6 flex items-center gap-3 text-xs font-medium uppercase tracking-wider text-faint">
      <span className="h-px flex-1 bg-line" />
      {label}
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

export const inputClass =
  "w-full rounded-xl border border-line bg-surface px-3.5 py-3 text-[15px] text-fg placeholder:text-faint transition focus:border-brand focus:outline-none focus:ring-4 focus:ring-[var(--ring)] aria-[invalid=true]:border-bad";
