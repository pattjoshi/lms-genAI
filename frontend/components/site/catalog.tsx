"use client";

import { BarChart3, BookOpen, BrainCircuit, Code2, Database, Layers, Users, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui";

export type CatalogCourse = {
  code: string;
  title: string;
  description: string;
  price_inr: number;
  teacher: string;
  category: string;
  level: string;
  modules: number;
  topics: string[];
  topic_count: number;
  learners: number;
};

export type Catalog = { courses: CatalogCourse[]; categories: string[] };

export const CATEGORY_STYLE: Record<string, { icon: LucideIcon; tone: string; blurb: string }> = {
  "AI and machine learning": {
    icon: BrainCircuit,
    tone: "from-[#6d5efc] to-[#b37bff]",
    blurb: "Models, neural networks and language AI",
  },
  Programming: { icon: Code2, tone: "from-[#0ea5e9] to-[#6366f1]", blurb: "Write real code from the first lesson" },
  Data: { icon: Database, tone: "from-[#10b981] to-[#0ea5e9]", blurb: "SQL, databases and working with data" },
  "Computer science": {
    icon: Layers,
    tone: "from-[#f59e0b] to-[#ef4444]",
    blurb: "Algorithms and how to think about problems",
  },
  More: { icon: BookOpen, tone: "from-[#64748b] to-[#334155]", blurb: "Everything else" },
};

export const inr = (n: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n);

export function CourseCard({ course }: { course: CatalogCourse }) {
  const style = CATEGORY_STYLE[course.category] ?? CATEGORY_STYLE.More;
  const Icon = style.icon;
  return (
    <article className="group relative flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card transition duration-200 hover:-translate-y-1 hover:border-brand/40 motion-reduce:transform-none">
      <div className={`relative h-28 bg-gradient-to-br ${style.tone}`}>
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_80%_20%,rgba(255,255,255,0.35),transparent_45%)]" />
        <Icon className="absolute bottom-3 right-4 h-14 w-14 text-white/35" aria-hidden />
        <span className="absolute left-4 top-4 rounded-full bg-black/25 px-2.5 py-1 font-mono text-[11px] font-medium text-white backdrop-blur">
          {course.code}
        </span>
      </div>
      <div className="flex flex-1 flex-col p-5">
        <p className="text-xs font-medium text-brand-ink">{course.category}</p>
        <h3 className="mt-1 font-display text-lg font-semibold leading-snug text-fg">
          {/* the whole card is the link target; the heading carries the accessible name */}
          <Link href={`/signup?course=${encodeURIComponent(course.code)}`} className="after:absolute after:inset-0">
            {course.title}
          </Link>
        </h3>
        <p className="mt-1.5 line-clamp-2 text-sm text-muted">{course.description}</p>
        <p className="mt-3 text-sm text-fg">
          <span className="text-muted">with</span> {course.teacher}
        </p>
        <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 pt-4 text-xs text-muted">
          <span className="inline-flex items-center gap-1">
            <BarChart3 className="h-3.5 w-3.5" aria-hidden /> {course.level}
          </span>
          <span className="inline-flex items-center gap-1">
            <BookOpen className="h-3.5 w-3.5" aria-hidden /> {course.modules} modules · {course.topic_count} topics
          </span>
          {course.learners > 0 && (
            <span className="inline-flex items-center gap-1">
              <Users className="h-3.5 w-3.5" aria-hidden /> {course.learners.toLocaleString("en-IN")} learners
            </span>
          )}
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-line pt-4">
          <span className="font-display text-base font-bold text-fg">{inr(course.price_inr)}</span>
          <span className="text-sm font-semibold text-brand-ink transition group-hover:translate-x-0.5">
            Enroll →
          </span>
        </div>
      </div>
    </article>
  );
}

export function CourseCardSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      <Skeleton className="h-28 rounded-none" />
      <div className="space-y-2.5 p-5">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-3.5" />
        <Skeleton className="h-3.5 w-2/3" />
      </div>
    </div>
  );
}
