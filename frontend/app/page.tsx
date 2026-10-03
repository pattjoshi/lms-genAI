"use client";

// Dummy login: pick any seeded user. Users with a planted "story" are listed first.

import { GraduationCap, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Alert, Avatar, Card, RoleBadge, Skeleton } from "@/components/ui";
import { useApi } from "@/components/useApi";
import { setUser, type SessionUser } from "@/lib/session";

type Health = Record<string, { ok: boolean; error?: string }>;

const SERVICES: Record<string, { label: string; fix: string }> = {
  postgres: { label: "Postgres", fix: "Run: docker compose up -d" },
  qdrant: { label: "Qdrant", fix: "Check: docker compose logs qdrant" },
  neo4j: { label: "Neo4j", fix: "Wait 60s after start. Auth error? See README troubleshooting" },
  openai: { label: "OpenAI key", fix: "Set OPENAI_API_KEY in .env and restart the backend" },
  langfuse: { label: "Langfuse", fix: "Set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY in .env" },
};

function UserCard({ user, onPick }: { user: SessionUser; onPick: (u: SessionUser) => void }) {
  return (
    <button
      onClick={() => onPick(user)}
      className="group flex items-start gap-3 rounded-xl border border-line bg-surface p-3.5 text-left transition hover:-translate-y-0.5 hover:border-brand/50 hover:shadow-card"
    >
      <Avatar name={user.full_name} role={user.role} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-medium text-fg group-hover:text-brand-ink">{user.full_name}</span>
          <RoleBadge role={user.role} />
        </div>
        <p className="mt-0.5 text-xs text-muted">{user.story ?? user.city}</p>
      </div>
    </button>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const health = useApi<Health>("/health");
  const users = useApi<SessionUser[]>("/auth/users");
  const [search, setSearch] = useState("");

  const all = users.data ?? [];
  const staff = all.filter((u) => u.role !== "student");
  const storyStudents = all.filter((u) => u.role === "student" && u.story);
  const others = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (users.data ?? [])
      .filter((u) => u.role === "student" && !u.story)
      .filter((u) => !q || u.full_name.toLowerCase().includes(q) || u.city.toLowerCase().includes(q));
  }, [users.data, search]);

  function login(user: SessionUser) {
    setUser(user);
    router.push(`/${user.role}`);
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* soft brand glow behind the header */}
      <div className="pointer-events-none absolute -top-40 left-1/2 h-80 w-[48rem] -translate-x-1/2 rounded-full bg-brand/15 blur-3xl" />

      <main className="relative mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand text-brand-fg">
              <GraduationCap className="h-5 w-5" />
            </span>
            <span className="font-display font-bold text-fg">LMS GenAI</span>
          </div>
          <ThemeToggle />
        </div>

        <h1 className="mt-10 font-display text-3xl font-bold text-fg sm:text-4xl">
          Pick a user to log in as
        </h1>
        <p className="mt-2 max-w-2xl text-muted">
          Dummy login for learning: no password. The backend still decides what each role is allowed to see.
        </p>

        {/* Service status */}
        <div className="mt-6 flex flex-wrap gap-2">
          {health.error && <Alert title={health.error.message} />}
          {!health.data && !health.error && <Skeleton className="h-7 w-96 rounded-full" />}
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
        {health.data && Object.values(health.data).some((s) => !s.ok) && (
          <p className="mt-2 text-xs text-faint">Hover a red service to see the error and how to fix it.</p>
        )}

        <div className="mt-8 grid gap-5">
          {users.error && <Alert title={users.error.message} detail={users.error.detail} />}
          {!users.data && !users.error && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-[68px] rounded-xl" />
              ))}
            </div>
          )}

          {users.data && (
            <>
              <Card title="Story students" subtitle="Each has a planted story in the data, good for testing">
                <div className="grid gap-3 sm:grid-cols-2">
                  {storyStudents.map((u) => (
                    <UserCard key={u.id} user={u} onPick={login} />
                  ))}
                </div>
              </Card>

              <Card title="Staff" subtitle="Admin, teachers and support">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {staff.map((u) => (
                    <UserCard key={u.id} user={u} onPick={login} />
                  ))}
                </div>
              </Card>

              <Card title={`All other students (${others.length})`}>
                <div className="relative mb-3">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search by name or city"
                    className="w-full rounded-xl border border-line bg-surface py-2.5 pl-9 pr-3 text-sm text-fg placeholder:text-faint focus:border-brand focus:outline-none"
                  />
                </div>
                <div className="grid max-h-80 gap-1 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-3">
                  {others.map((u) => (
                    <button
                      key={u.id}
                      onClick={() => login(u)}
                      className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-surface-2"
                    >
                      <Avatar name={u.full_name} role="student" size="sm" />
                      <span className="flex-1 truncate text-fg">{u.full_name}</span>
                      <span className="text-xs text-faint">{u.city}</span>
                    </button>
                  ))}
                </div>
              </Card>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
