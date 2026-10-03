"use client";

// Layout + role guard for every portal page. If nobody is logged in, or the
// logged-in user has a different role, go back to the login page.
// (This is only UX — the backend enforces roles on every request.)

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { ROADMAP } from "@/lib/features";
import { clearUser, getUser, type Role, type SessionUser } from "@/lib/session";
import { Card } from "./ui";

const TITLES: Record<Role, string> = {
  student: "Student portal",
  teacher: "Teacher portal",
  admin: "Admin portal",
  support: "Support portal",
};

export function PortalShell({ role, children }: { role: Role; children: (user: SessionUser) => ReactNode }) {
  const router = useRouter();
  const [user, setUserState] = useState<SessionUser | null>(null);

  useEffect(() => {
    const current = getUser();
    if (!current || current.role !== role) router.replace("/");
    else setUserState(current);
  }, [role, router]);

  if (!user) return null;

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-indigo-600">LMS GenAI</p>
            <h1 className="text-lg font-semibold text-slate-900">{TITLES[role]}</h1>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right text-sm">
              <p className="font-medium text-slate-900">{user.full_name}</p>
              <p className="text-slate-500">{user.email}</p>
            </div>
            <button
              onClick={() => {
                clearUser();
                router.replace("/");
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto grid max-w-6xl gap-4 px-4 py-6">
        {children(user)}
        <Card title="Coming next" subtitle="Core features of this portal and the phase that builds them">
          <ul className="grid gap-2 sm:grid-cols-2">
            {ROADMAP[role].map((f) => (
              <li key={f.id} className="flex items-center gap-2 text-sm text-slate-700">
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">{f.id}</span>
                <span className="flex-1">{f.name}</span>
                <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">Phase {f.phase}</span>
              </li>
            ))}
          </ul>
        </Card>
      </main>
    </div>
  );
}
