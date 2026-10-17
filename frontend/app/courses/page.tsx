"use client";

// Public course catalogue: search, filter by category and level, sort. Filters live in the URL so a
// filtered view can be shared or bookmarked.

import { SearchX, SlidersHorizontal } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";

import { CourseCard, CourseCardSkeleton, type Catalog } from "@/components/site/catalog";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";
import { Alert } from "@/components/ui";
import { useApi } from "@/components/useApi";

const LEVELS = ["Beginner", "Intermediate", "Advanced"];
const SORTS: Record<string, string> = { popular: "Most popular", price_low: "Price: low to high", title: "A to Z" };

function CatalogView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { data, error } = useApi<Catalog>("/public/catalog");

  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const level = params.get("level") ?? "";
  const sort = params.get("sort") ?? "popular";

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  const courses = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = (data?.courses ?? []).filter(
      (c) =>
        (!category || c.category === category) &&
        (!level || c.level === level) &&
        (!needle ||
          [c.title, c.description, c.teacher, c.code, ...c.topics].some((t) => t.toLowerCase().includes(needle))),
    );
    const by: Record<string, (a: (typeof list)[0], b: (typeof list)[0]) => number> = {
      popular: (a, b) => b.learners - a.learners,
      price_low: (a, b) => a.price_inr - b.price_inr,
      title: (a, b) => a.title.localeCompare(b.title),
    };
    return list.sort(by[sort] ?? by.popular);
  }, [data, q, category, level, sort]);

  const filtering = Boolean(q || category || level);
  const control =
    "w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-fg focus:border-brand focus:outline-none";

  return (
    <main id="main" className="mx-auto max-w-7xl px-4 pb-20 pt-8 sm:px-6 sm:pt-12">
      <h1 className="font-display text-3xl font-bold tracking-tight text-fg sm:text-4xl">Explore courses</h1>
      <p className="mt-2 max-w-2xl text-muted">
        Every course comes with the AI tutor: ask about any lesson and get an answer with its source.
      </p>

      <div className="sticky top-16 z-20 -mx-4 mt-8 border-y border-line bg-bg/90 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-2xl sm:border sm:px-4">
        <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr_1fr]">
          <div>
            <label htmlFor="q" className="sr-only">
              Search courses
            </label>
            <input
              id="q"
              type="search"
              defaultValue={q}
              onChange={(e) => set("q", e.target.value)}
              placeholder="Search by course, topic or instructor"
              className={control}
            />
          </div>
          <div>
            <label htmlFor="category" className="sr-only">
              Category
            </label>
            <select id="category" value={category} onChange={(e) => set("category", e.target.value)} className={control}>
              <option value="">All categories</option>
              {(data?.categories ?? []).map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="level" className="sr-only">
              Level
            </label>
            <select id="level" value={level} onChange={(e) => set("level", e.target.value)} className={control}>
              <option value="">All levels</option>
              {LEVELS.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="sort" className="sr-only">
              Sort by
            </label>
            <select id="sort" value={sort} onChange={(e) => set("sort", e.target.value)} className={control}>
              {Object.entries(SORTS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between text-sm text-muted" aria-live="polite">
        <span className="inline-flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4" aria-hidden />
          {data ? `${courses.length} course${courses.length === 1 ? "" : "s"}` : "Loading courses…"}
        </span>
        {filtering && (
          <button
            type="button"
            onClick={() => router.replace(pathname, { scroll: false })}
            className="font-semibold text-brand-ink hover:underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {error && (
        <div className="mt-6">
          <Alert title={error.message} detail={error.detail} />
        </div>
      )}

      <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {!data && !error && Array.from({ length: 6 }, (_, i) => <CourseCardSkeleton key={i} />)}
        {courses.map((c) => (
          <CourseCard key={c.code} course={c} />
        ))}
      </div>

      {data && courses.length === 0 && (
        <div className="mt-6 flex flex-col items-center rounded-3xl border border-dashed border-line px-6 py-16 text-center">
          <SearchX className="h-8 w-8 text-faint" aria-hidden />
          <p className="mt-3 font-display text-lg font-semibold text-fg">No courses match</p>
          <p className="mt-1 text-sm text-muted">Try a shorter search or another category.</p>
        </div>
      )}
    </main>
  );
}

export default function CoursesPage() {
  return (
    <>
      <SiteHeader />
      <Suspense fallback={<main className="mx-auto min-h-[60vh] max-w-7xl px-4" />}>
        <CatalogView />
      </Suspense>
      <SiteFooter />
    </>
  );
}
