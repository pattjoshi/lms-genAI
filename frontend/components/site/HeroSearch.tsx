"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

const SUGGESTIONS = ["Python", "Machine learning", "SQL joins", "Neural networks"];

export function HeroSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const go = (term: string) => router.push(`/courses?q=${encodeURIComponent(term.trim())}`);

  return (
    <div>
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          go(q);
        }}
        className="flex items-center gap-2 rounded-2xl border border-line bg-surface p-1.5 pl-4 shadow-card focus-within:border-brand focus-within:ring-4 focus-within:ring-[var(--ring)]"
      >
        <Search className="h-5 w-5 shrink-0 text-faint" aria-hidden />
        <label htmlFor="hero-search" className="sr-only">
          What do you want to learn?
        </label>
        <input
          id="hero-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="What do you want to learn?"
          className="min-w-0 flex-1 bg-transparent py-2 text-[15px] text-fg placeholder:text-faint focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-xl bg-fg px-4 py-2.5 text-sm font-semibold text-bg transition-opacity hover:opacity-90"
        >
          Search
        </button>
      </form>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-faint">Popular:</span>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => go(s)}
            className="rounded-full border border-line bg-surface/70 px-3 py-1 text-muted transition-colors hover:border-brand/50 hover:text-fg"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
