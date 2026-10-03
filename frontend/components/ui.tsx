// Small shared UI kit. Colours come from the design tokens in globals.css,
// so everything here works in light and dark mode without extra classes.

import { CircleCheck, Inbox, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import type { Role } from "@/lib/session";

export function Card({
  title,
  subtitle,
  icon,
  action,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-line bg-surface p-5 shadow-card ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            {icon && (
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-ink">
                {icon}
              </span>
            )}
            <div>
              {title && <h2 className="font-display text-[15px] font-semibold text-fg">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
            </div>
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" }) {
  const styles =
    variant === "primary"
      ? "bg-brand text-brand-fg hover:bg-brand-hover"
      : "border border-line bg-surface text-fg hover:bg-surface-2";
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

export function Alert({
  tone = "bad",
  title,
  detail,
}: {
  tone?: "bad" | "ok" | "warn";
  title: string;
  detail?: string;
}) {
  const styles = {
    bad: "border-bad/30 bg-bad-soft text-bad",
    warn: "border-warn/30 bg-warn-soft text-warn",
    ok: "border-ok/30 bg-ok-soft text-ok",
  }[tone];
  const Icon = tone === "ok" ? CircleCheck : TriangleAlert;
  return (
    <div className={`flex gap-2.5 rounded-xl border p-3 text-sm ${styles}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">
        <p className="font-medium">{title}</p>
        {detail && <p className="mt-1 break-words font-mono text-xs opacity-80">{detail}</p>}
      </div>
    </div>
  );
}

export function Stat({ label, value, hint, mono }: { label: string; value: ReactNode; hint?: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2/60 p-3.5">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className={`mt-1 text-xl font-semibold text-fg ${mono ? "font-mono text-lg" : "font-display"}`}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-faint">{hint}</p>}
    </div>
  );
}

export function Chip({ children, mono }: { children: ReactNode; mono?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-xs text-muted ${mono ? "font-mono" : ""}`}
    >
      {children}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`relative overflow-hidden rounded-lg bg-surface-2 ${className}`}>
      <div className="absolute inset-0 -translate-x-full animate-[shimmer_1.4s_infinite] bg-gradient-to-r from-transparent via-line/60 to-transparent" />
    </div>
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">
      <Skeleton className="h-4 w-40" />
      <div className="mt-4 space-y-2.5">
        {Array.from({ length: lines }, (_, i) => (
          <Skeleton key={i} className="h-3.5" />
        ))}
      </div>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line px-4 py-8 text-center">
      <Inbox className="h-6 w-6 text-faint" />
      <p className="mt-2 text-sm font-medium text-fg">{title}</p>
      {hint && <p className="mt-1 text-sm text-muted">{hint}</p>}
    </div>
  );
}

// ---- Role styling -----------------------------------------------------------

export const ROLE_STYLE: Record<Role, { text: string; soft: string; bar: string }> = {
  student: { text: "text-student", soft: "bg-student-soft", bar: "bg-student" },
  teacher: { text: "text-teacher", soft: "bg-teacher-soft", bar: "bg-teacher" },
  admin: { text: "text-admin", soft: "bg-admin-soft", bar: "bg-admin" },
  support: { text: "text-support", soft: "bg-support-soft", bar: "bg-support" },
};

export function RoleBadge({ role }: { role: Role }) {
  const s = ROLE_STYLE[role];
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${s.soft} ${s.text}`}>{role}</span>;
}

export function Avatar({ name, role, size = "md" }: { name: string; role: Role; size?: "sm" | "md" }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
  const s = ROLE_STYLE[role];
  const dim = size === "sm" ? "h-8 w-8 text-xs" : "h-10 w-10 text-sm";
  return (
    <span className={`flex shrink-0 items-center justify-center rounded-full font-display font-semibold ${dim} ${s.soft} ${s.text}`}>
      {initials}
    </span>
  );
}

export function ProgressBar({ value, tone = "bg-brand" }: { value: number; tone?: string }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-surface-2">
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function ScoreText({ score }: { score: number }) {
  const tone = score < 50 ? "text-bad" : score < 65 ? "text-warn" : "text-ok";
  return <span className={`font-mono text-sm font-medium ${tone}`}>{score}%</span>;
}
