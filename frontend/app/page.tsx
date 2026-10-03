"use client";

// Dummy login: pick any seeded user. Users with a planted "story" are listed first.

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Card, ErrorBox, Loading } from "@/components/ui";
import { useApi } from "@/components/useApi";
import { setUser, type Role, type SessionUser } from "@/lib/session";

type Health = Record<string, { ok: boolean; error?: string }>;

const ROLE_STYLE: Record<Role, string> = {
  admin: "bg-purple-50 text-purple-700",
  teacher: "bg-emerald-50 text-emerald-700",
  support: "bg-amber-50 text-amber-700",
  student: "bg-sky-50 text-sky-700",
};

const SERVICE_LABELS: Record<string, string> = {
  postgres: "Postgres",
  qdrant: "Qdrant",
  neo4j: "Neo4j",
  openai: "OpenAI key",
  langfuse: "Langfuse",
};

export default function LoginPage() {
  const router = useRouter();
  const health = useApi<Health>("/health");
  const users = useApi<SessionUser[]>("/auth/users");
  const [search, setSearch] = useState("");

  const featured = useMemo(() => (users.data ?? []).filter((u) => u.role !== "student" || u.story), [users.data]);
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
    <main className="mx-auto max-w-5xl px-4 py-10">
      <p className="text-sm font-medium uppercase tracking-wide text-indigo-600">LMS GenAI</p>
      <h1 className="mt-1 text-2xl font-semibold">Pick a user to log in as</h1>
      <p className="mt-1 text-sm text-slate-600">
        Dummy login for learning: no password. The backend still enforces what each role can see.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {health.error && <ErrorBox message={health.error.message} />}
        {health.data &&
          Object.entries(health.data).map(([name, s]) => (
            <span
              key={name}
              title={s.error ?? "OK"}
              className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs"
            >
              <span className={`h-2 w-2 rounded-full ${s.ok ? "bg-emerald-500" : "bg-red-500"}`} />
              {SERVICE_LABELS[name] ?? name}
            </span>
          ))}
      </div>

      <div className="mt-6 grid gap-4">
        {users.error && <ErrorBox message={users.error.message} detail={users.error.detail} />}
        {!users.data && !users.error && <Loading />}

        {users.data && (
          <>
            <Card title="Staff and story students" subtitle="Students with a planted story are useful to test with">
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {featured.map((u) => (
                  <button
                    key={u.id}
                    onClick={() => login(u)}
                    className="rounded-lg border border-slate-200 p-3 text-left hover:border-indigo-400 hover:bg-indigo-50/40"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{u.full_name}</span>
                      <span className={`rounded-full px-2 py-0.5 text-xs ${ROLE_STYLE[u.role]}`}>{u.role}</span>
                    </div>
                    {u.story && <p className="mt-1 text-xs text-slate-600">{u.story}</p>}
                  </button>
                ))}
              </div>
            </Card>

            <Card title={`Other students (${others.length})`}>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name or city"
                className="mb-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
              />
              <div className="grid max-h-72 gap-1 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
                {others.map((u) => (
                  <button
                    key={u.id}
                    onClick={() => login(u)}
                    className="flex justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-slate-100"
                  >
                    <span>{u.full_name}</span>
                    <span className="text-slate-500">{u.city}</span>
                  </button>
                ))}
              </div>
            </Card>
          </>
        )}
      </div>
    </main>
  );
}
