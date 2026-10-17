"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { useApi } from "@/components/useApi";
import { CATEGORY_STYLE, CourseCard, CourseCardSkeleton, type Catalog } from "./catalog";

type Stats = { learners: number; instructors: number; courses: number; questions_answered: number };

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k+` : `${n}`);

/** Live totals from the backend; the hero still reads well while they load or if the backend is off. */
export function LiveStats() {
  const { data } = useApi<Stats>("/public/stats");
  const items = [
    { label: "learners", value: data?.learners },
    { label: "expert instructors", value: data?.instructors },
    // A fresh install has answered nothing yet; show the catalogue size until it has.
    data && data.questions_answered > 0
      ? { label: "questions answered by the AI tutor", value: data.questions_answered }
      : { label: "courses, each with an AI tutor", value: data?.courses },
  ];
  return (
    <dl className="grid grid-cols-3 gap-4 border-t border-line pt-6 sm:max-w-lg">
      {items.map((s) => (
        <div key={s.label}>
          <dt className="sr-only">{s.label}</dt>
          <dd className="font-display text-2xl font-bold text-fg sm:text-3xl">
            {s.value === undefined ? <span className="text-faint">—</span> : fmt(s.value)}
          </dd>
          <dd aria-hidden className="mt-0.5 text-xs leading-snug text-muted sm:text-sm">
            {s.label}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function CategoryGrid() {
  const { data } = useApi<Catalog>("/public/catalog");
  const counts = new Map<string, number>();
  data?.courses.forEach((c) => counts.set(c.category, (counts.get(c.category) ?? 0) + 1));
  const categories = data?.categories.length
    ? data.categories
    : ["AI and machine learning", "Programming", "Data", "Computer science"];

  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {categories.map((name) => {
        const style = CATEGORY_STYLE[name] ?? CATEGORY_STYLE.More;
        const Icon = style.icon;
        const n = counts.get(name);
        return (
          <li key={name}>
            <Link
              href={`/courses?category=${encodeURIComponent(name)}`}
              className="group flex h-full items-start gap-4 rounded-2xl border border-line bg-surface p-5 shadow-card transition hover:-translate-y-0.5 hover:border-brand/40 motion-reduce:transform-none"
            >
              <span
                className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-white ${style.tone}`}
              >
                <Icon className="h-6 w-6" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block font-display font-semibold text-fg group-hover:text-brand-ink">{name}</span>
                <span className="mt-0.5 block text-sm text-muted">{style.blurb}</span>
                {n !== undefined && (
                  <span className="mt-2 block text-xs font-medium text-faint">
                    {n} course{n === 1 ? "" : "s"}
                  </span>
                )}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function FeaturedCourses() {
  const { data, error } = useApi<Catalog>("/public/catalog");
  const courses = [...(data?.courses ?? [])].sort((a, b) => b.learners - a.learners).slice(0, 6);

  if (error || (data && courses.length === 0)) {
    return (
      <div className="rounded-2xl border border-dashed border-line p-10 text-center">
        <p className="font-medium text-fg">The course catalogue is loading slowly.</p>
        <p className="mt-1 text-sm text-muted">
          <Link href="/courses" className="font-semibold text-brand-ink hover:underline">
            Open the full catalogue
          </Link>{" "}
          to try again.
        </p>
      </div>
    );
  }
  return (
    <>
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {data ? courses.map((c) => <CourseCard key={c.code} course={c} />) : [0, 1, 2].map((i) => <CourseCardSkeleton key={i} />)}
      </div>
      <div className="mt-8 text-center">
        <Link
          href="/courses"
          className="inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-5 py-2.5 text-sm font-semibold text-fg shadow-card hover:bg-surface-2"
        >
          See all courses <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      </div>
    </>
  );
}
