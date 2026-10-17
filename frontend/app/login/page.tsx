"use client";

import { ChevronDown, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { DemoLogin } from "@/components/DemoLogin";
import { AuthShell, Divider, inputClass } from "@/components/site/AuthShell";
import { GoogleButton } from "@/components/site/GoogleButton";
import { PasswordField } from "@/components/site/PasswordField";
import { useAuthConfig } from "@/components/site/useAuthConfig";
import { Alert } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";
import { fetchMe, homeFor, setUser, type SessionUser } from "@/lib/session";

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const config = useAuthConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = useCallback(
    (user: SessionUser) => {
      setUser(user);
      router.replace(homeFor(user, next));
    },
    [router, next],
  );

  // Already logged in? Go straight to the portal.
  useEffect(() => {
    fetchMe()
      .then((me) => me && router.replace(homeFor(me, next)))
      .catch(() => undefined);
  }, [router, next]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      done(await apiFetch<SessionUser>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(false);
    }
  }

  const googleId = config.data?.google_client_id;

  return (
    <>
      <h1 className="font-display text-3xl font-bold tracking-tight text-fg">Welcome back</h1>
      <p className="mt-2 text-muted">
        Log in to continue learning.{" "}
        {config.data?.signup_open !== false && (
          <>
            New here?{" "}
            <Link href="/signup" className="font-semibold text-brand-ink hover:underline">
              Create an account
            </Link>
          </>
        )}
      </p>

      {next && (
        <p className="mt-4 rounded-xl border border-line bg-surface-2/60 px-3 py-2 text-sm text-muted">
          Log in to open that page.
        </p>
      )}

      {googleId && (
        <>
          <div className="mt-8">
            <GoogleButton clientId={googleId} text="signin_with" onSignedIn={done} onError={setError} />
          </div>
          <Divider label="or with email" />
        </>
      )}

      <form onSubmit={submit} className={`grid gap-4 ${googleId ? "" : "mt-8"}`} noValidate={false}>
        {error && (
          <div role="alert">
            <Alert title={error} />
          </div>
        )}
        <div>
          <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-fg">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
            autoFocus
            className={inputClass}
            placeholder="you@example.com"
          />
        </div>
        <PasswordField value={password} onChange={setPassword} autoComplete="current-password" />
        <details className="-mt-1 text-sm">
          <summary className="cursor-pointer list-none text-right font-medium text-brand-ink hover:underline [&::-webkit-details-marker]:hidden">
            Forgot your password?
          </summary>
          <p className="mt-2 rounded-xl bg-surface-2/70 p-3 text-muted">
            If you signed up with Google, use the Google button. Otherwise ask your admin to reset it: they can run{" "}
            <code className="font-mono text-xs">python -m app.accounts set-password</code>.
          </p>
        </details>
        <button
          type="submit"
          disabled={busy}
          className="mt-1 inline-flex items-center justify-center gap-2 rounded-xl bg-brand px-4 py-3 font-semibold text-brand-fg transition-colors hover:bg-brand-hover disabled:opacity-60"
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>

      {config.error && (
        <div className="mt-6">
          <Alert tone="warn" title={config.error.message} />
        </div>
      )}

      {config.data?.demo_login && (
        <details className="group mt-10 rounded-2xl border border-dashed border-line p-4">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 [&::-webkit-details-marker]:hidden">
            <span>
              <span className="block text-sm font-semibold text-fg">Demo accounts (development only)</span>
              <span className="block text-xs text-muted">Log in as any seeded user without a password</span>
            </span>
            <ChevronDown className="h-4 w-4 text-muted transition-transform group-open:rotate-180" aria-hidden />
          </summary>
          <div className="mt-4">
            <DemoLogin onLoggedIn={done} />
          </div>
        </details>
      )}
    </>
  );
}

export default function LoginPage() {
  return (
    <AuthShell>
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
