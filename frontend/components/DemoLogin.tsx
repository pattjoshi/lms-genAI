"use client";

// Demo login (dev only): pick any seeded user. They have no passwords; the backend still issues a real
// session and decides what each role may see. Users with a planted "story" are listed first.

import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Alert, Avatar, RoleBadge, Skeleton } from "@/components/ui";
import { useApi } from "@/components/useApi";
import { apiFetch, ApiError } from "@/lib/api";
import type { SessionUser } from "@/lib/session";

type Health = Record<string, { ok: boolean; error?: string }>;

const SERVICES: Record<string, { label: string; fix: string }> = {
  postgres: { label: "Postgres", fix: "Run: docker compose up -d" },
  qdrant: { label: "Qdrant", fix: "Check: docker compose logs qdrant" },
  neo4j: { label: "Neo4j", fix: "Wait 60s after start. Auth error? See README troubleshooting" },
  openai: { label: "OpenAI key", fix: "Set OPENAI_API_KEY in .env and restart the backend" },
  langfuse: { label: "Langfuse", fix: "Set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY in .env" },
};

function UserCard({ user, onPick, busy }: { user: SessionUser; onPick: (u: SessionUser) => void; busy: boolean }) {
  return (
    <button
      type="button"
      onClick={() => onPick(user)}
      disabled={busy}
      className="group flex items-start gap-3 rounded-xl border border-line bg-surface p-3 text-left transition hover:-translate-y-0.5 hover:border-brand/50 hover:shadow-card disabled:opacity-60"
    >
      <Avatar name={user.full_name} role={user.role} size="sm" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium text-fg group-hover:text-brand-ink">{user.full_name}</span>
          <RoleBadge role={user.role} />
        </div>
        <p className="mt-0.5 line-clamp-2 text-xs text-muted">{user.story ?? user.city}</p>
      </div>
    </button>
  );
}

export function DemoLogin({ onLoggedIn }: { onLoggedIn: (user: SessionUser) => void }) {
  const health = useApi<Health>("/health");
  const users = useApi<SessionUser[]>("/auth/users");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const all = users.data ?? [];
  const staff = all.filter((u) => u.role !== "student");
  const storyStudents = all.filter((u) => u.role === "student" && u.story);
  const others = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (users.data ?? [])
      .filter((u) => u.role === "student" && !u.story)
      .filter((u) => !q || u.full_name.toLowerCase().includes(q) || u.city.toLowerCase().includes(q));
  }, [users.data, search]);

  async function pick(user: SessionUser) {
    setBusy(true);
    setError(null);
    try {
      onLoggedIn(await apiFetch<SessionUser>("/auth/demo-login", { method: "POST", body: JSON.stringify({ user_id: user.id }) }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap gap-2">
        {health.error && <Alert title={health.error.message} />}
        {!health.data && !health.error && <Skeleton className="h-7 w-80 rounded-full" />}
        {health.data &&
          Object.entries(SERVICES).map(([key, meta]) => {
            const s = health.data?.[key];
            if (!s) return null;
            return (
              <span
                key={key}
                title={s.ok ? "Connected" : `${s.error ?? "Not configured"}\n\nFix: ${meta.fix}`}
                className={`flex cursor-default items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
                  s.ok ? "border-ok/30 bg-ok-soft text-ok" : "border-bad/30 bg-bad-soft text-bad"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${s.ok ? "bg-ok" : "bg-bad"}`} />
                {meta.label}
              </span>
            );
          })}
      </div>

      {error && <Alert title={error} />}
      {users.error && <Alert title={users.error.message} detail={users.error.detail} />}
      {!users.data && !users.error && (
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-[62px] rounded-xl" />
          ))}
        </div>
      )}

      {users.data && (
        <>
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Staff</h3>
            <div className="grid gap-2.5 sm:grid-cols-2">
              {staff.map((u) => (
                <UserCard key={u.id} user={u} onPick={pick} busy={busy} />
              ))}
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Story students</h3>
            <div className="grid gap-2.5 sm:grid-cols-2">
              {storyStudents.map((u) => (
                <UserCard key={u.id} user={u} onPick={pick} busy={busy} />
              ))}
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">
              All other students ({others.length})
            </h3>
            <div className="relative mb-2">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name or city"
                aria-label="Search demo students"
                className="w-full rounded-xl border border-line bg-surface py-2 pl-9 pr-3 text-sm text-fg placeholder:text-faint focus:border-brand focus:outline-none"
              />
            </div>
            <div className="grid max-h-64 gap-1 overflow-y-auto pr-1 sm:grid-cols-2">
              {others.map((u) => (
                <button
                  type="button"
                  key={u.id}
                  disabled={busy}
                  onClick={() => pick(u)}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-surface-2"
                >
                  <Avatar name={u.full_name} role="student" size="sm" />
                  <span className="flex-1 truncate text-fg">{u.full_name}</span>
                  <span className="text-xs text-faint">{u.city}</span>
                </button>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
