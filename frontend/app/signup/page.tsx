"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useState } from "react";

import { AuthShell, Divider, inputClass } from "@/components/site/AuthShell";
import { GoogleButton } from "@/components/site/GoogleButton";
import { PasswordField } from "@/components/site/PasswordField";
import { useAuthConfig } from "@/components/site/useAuthConfig";
import { Alert } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";
import { homeFor, setUser, type SessionUser } from "@/lib/session";

const PLAN_NOTE: Record<string, string> = {
  plus: "You picked Plus. Create your account first; you can upgrade from your dashboard.",
  teams: "Setting up for a team? Create your account, then we'll help you add your people.",
};

function SignupForm() {
  const router = useRouter();
  const params = useSearchParams();
  const course = params.get("course");
  const plan = params.get("plan");
  const config = useAuthConfig();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = useCallback(
    (user: SessionUser) => {
      setUser(user);
      router.replace(homeFor(user));
    },
    [router],
  );

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      done(
        await apiFetch<SessionUser>("/auth/signup", {
          method: "POST",
          body: JSON.stringify({ full_name: fullName, email, password }),
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(false);
    }
  }

  if (config.data && !config.data.signup_open) {
    return (
      <>
        <h1 className="font-display text-3xl font-bold tracking-tight text-fg">Sign-up is closed</h1>
        <p className="mt-2 text-muted">Ask your organisation&apos;s admin to create an account for you.</p>
        <Link href="/login" className="mt-6 font-semibold text-brand-ink hover:underline">
          Go to log in
        </Link>
      </>
    );
  }

  const googleId = config.data?.google_client_id;
  const minLength = config.data?.password_min_length ?? 8;

  return (
    <>
      <h1 className="font-display text-3xl font-bold tracking-tight text-fg">Create your free account</h1>
      <p className="mt-2 text-muted">
        Already have one?{" "}
        <Link href="/login" className="font-semibold text-brand-ink hover:underline">
          Log in
        </Link>
      </p>

      {(course || (plan && PLAN_NOTE[plan])) && (
        <p className="mt-4 rounded-xl border border-brand/30 bg-brand-soft px-3 py-2 text-sm text-brand-ink">
          {course ? `Sign up to enroll in ${course}.` : PLAN_NOTE[plan!]}
        </p>
      )}

      {googleId && (
        <>
          <div className="mt-8">
            <GoogleButton clientId={googleId} text="signup_with" onSignedIn={done} onError={setError} />
          </div>
          <Divider label="or with email" />
        </>
      )}

      <form onSubmit={submit} className={`grid gap-4 ${googleId ? "" : "mt-8"}`}>
        {error && (
          <div role="alert">
            <Alert title={error} />
          </div>
        )}
        <div>
          <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-fg">
            Full name
          </label>
          <input
            id="name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            autoComplete="name"
            required
            minLength={2}
            maxLength={120}
            autoFocus
            className={inputClass}
            placeholder="Asha Rao"
          />
        </div>
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
            maxLength={200}
            className={inputClass}
            placeholder="you@example.com"
          />
        </div>
        <PasswordField
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          showStrength
          minLength={minLength}
        />
        <button
          type="submit"
          disabled={busy}
          className="mt-1 inline-flex items-center justify-center gap-2 rounded-xl bg-brand px-4 py-3 font-semibold text-brand-fg transition-colors hover:bg-brand-hover disabled:opacity-60"
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
          {busy ? "Creating your account…" : "Create account"}
        </button>
        <p className="text-center text-xs text-faint">
          New accounts are student accounts. Instructors and staff get their role from an admin.
        </p>
      </form>
    </>
  );
}

export default function SignupPage() {
  return (
    <AuthShell>
      <Suspense>
        <SignupForm />
      </Suspense>
    </AuthShell>
  );
}
