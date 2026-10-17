"use client";

// Layout + role guard for every portal: sidebar (desktop) / slide-in menu (mobile),
// top bar with page title and theme toggle, and the roadmap card at the bottom.
// The guard here is only UX (who sees which screens): the backend checks the session cookie and the
// role on every request. Not logged in -> /login?next=<this page>; another role -> their own portal.

import { GraduationCap, LogOut, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { UNAUTHORIZED_EVENT } from "@/lib/api";
import { CURRENT_PHASE, NAV, ROADMAP } from "@/lib/features";
import { fetchMe, getUser, logout as endSession, type Role, type SessionUser } from "@/lib/session";
import { ThemeToggle } from "./ThemeToggle";
import { Alert, Avatar, Card, ROLE_STYLE, Skeleton } from "./ui";

const TITLES: Record<Role, string> = {
  student: "Student portal",
  teacher: "Teacher portal",
  admin: "Admin portal",
  support: "Support portal",
};

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand text-brand-fg">
        <GraduationCap className="h-5 w-5" />
      </span>
      <div className="leading-tight">
        <p className="font-display text-sm font-bold text-fg">LMS GenAI</p>
        <p className="text-xs text-muted">Learning assistant</p>
      </div>
    </div>
  );
}

function Sidebar({ role, user, onLogout }: { role: Role; user: SessionUser; onLogout: () => void }) {
  const pathname = usePathname();
  return (
    <div className="flex h-full flex-col gap-6 p-4">
      <Brand />
      <nav className="flex-1 space-y-1">
        {NAV[role].map(({ label, icon: Icon, href, phase }) => {
          if (!href) {
            return (
              <div
                key={label}
                aria-disabled
                title={`Arrives in Phase ${phase}`}
                className="flex cursor-not-allowed items-center gap-3 rounded-xl px-3 py-2 text-sm text-faint"
              >
                <Icon className="h-4 w-4" />
                <span className="flex-1">{label}</span>
                <span className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[10px]">P{phase}</span>
              </div>
            );
          }
          const active = pathname === href;
          return (
            <Link
              key={label}
              href={href}
              className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors ${
                active ? "bg-brand-soft font-medium text-brand-ink" : "text-muted hover:bg-surface-2 hover:text-fg"
              }`}
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1">{label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="rounded-xl border border-line bg-surface-2/60 p-3">
        <div className="flex items-center gap-3">
          <Avatar name={user.full_name} role={role} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-fg">{user.full_name}</p>
            <p className={`text-xs capitalize ${ROLE_STYLE[role].text}`}>{role}</p>
          </div>
          <button
            onClick={onLogout}
            title="Log out"
            className="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-fg"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

export function PortalShell({
  role,
  title,
  showRoadmap = true,
  children,
}: {
  role: Role;
  title?: string;
  showRoadmap?: boolean;
  children: (user: SessionUser) => ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUserState] = useState<SessionUser | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const toLogin = () => router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    // Show the cached user at once (no blank page), then confirm with the backend.
    const cached = getUser();
    if (cached?.role === role) setUserState(cached);
    let cancelled = false;
    fetchMe()
      .then((me) => {
        if (cancelled) return;
        if (!me) toLogin();
        else if (me.role !== role) router.replace(`/${me.role}`);
        else setUserState(me);
      })
      .catch((e) => !cancelled && setCheckError(e instanceof Error ? e.message : String(e)));
    window.addEventListener(UNAUTHORIZED_EVENT, toLogin);
    return () => {
      cancelled = true;
      window.removeEventListener(UNAUTHORIZED_EVENT, toLogin);
    };
  }, [role, router]);

  useEffect(() => setMenuOpen(false), [pathname]);

  if (checkError && !user) {
    return (
      <main className="mx-auto max-w-lg px-4 py-16">
        <Alert title={checkError} />
      </main>
    );
  }
  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center" aria-busy="true" aria-label="Checking your login">
        <Skeleton className="h-10 w-48 rounded-xl" />
      </div>
    );
  }

  const logout = async () => {
    await endSession().catch(() => undefined);
    router.replace("/");
  };

  return (
    <div className="min-h-screen lg:pl-64">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-line bg-surface lg:block">
        <Sidebar role={role} user={user} onLogout={logout} />
      </aside>

      {/* Mobile slide-in menu */}
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMenuOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 border-r border-line bg-surface">
            <button
              onClick={() => setMenuOpen(false)}
              className="absolute right-3 top-4 rounded-lg p-1.5 text-muted hover:bg-surface-2"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" />
            </button>
            <Sidebar role={role} user={user} onLogout={logout} />
          </aside>
        </div>
      )}

      <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMenuOpen(true)}
              className="rounded-lg p-1.5 text-muted hover:bg-surface-2 lg:hidden"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div>
              <h1 className="font-display text-lg font-bold text-fg">{title ?? TITLES[role]}</h1>
              <p className="hidden text-xs text-muted sm:block">Welcome back, {user.full_name.split(" ")[0]}</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-5 px-4 py-6 sm:px-6">
        {children(user)}
        {showRoadmap && (
          <Card title="Coming next" subtitle="Core features of this portal and the phase that builds them">
            <ul className="grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
              {ROADMAP[role].map((f) => (
                <li key={f.id} className="flex items-center gap-2.5 text-sm text-fg">
                  <span className="w-9 shrink-0 font-mono text-xs text-faint">{f.id}</span>
                  <span className="flex-1">{f.name}</span>
                  {f.live || f.phase <= CURRENT_PHASE ? (
                    <span className="rounded-full bg-ok-soft px-2 py-0.5 text-xs font-medium text-ok">Live</span>
                  ) : (
                    <span className="rounded-full bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand-ink">
                      Phase {f.phase}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </main>
    </div>
  );
}
