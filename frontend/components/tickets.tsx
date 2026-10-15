// Phase 5: small pieces shared by the ticket pages (student, support, admin).

import type { ReactNode } from "react";

export type TicketRow = {
  id: number;
  subject: string;
  reason: string;
  category: string;
  status: "open" | "in_progress" | "resolved";
  student: string | null;
  course_code: string | null;
  assigned_to: string | null;
  doubt_id: number | null;
  resolution: string | null;
  saved_to_kb: boolean;
  created_at: string | null;
  resolved_at: string | null;
};

export const REASON_LABEL: Record<string, string> = {
  no_answer: "AI had no answer",
  low_confidence: "Low confidence",
  thumbs_down: "👎 from student",
  support: "Login / payment",
  student: "Asked by student",
};

export const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
};

const STATUS_STYLE: Record<string, string> = {
  open: "border-warn/30 bg-warn-soft text-warn",
  in_progress: "border-brand/30 bg-brand-soft text-brand-ink",
  resolved: "border-ok/30 bg-ok-soft text-ok",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[status] ?? ""}`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">
      {children}
    </span>
  );
}

export function ago(iso: string | null) {
  if (!iso) return "";
  const mins = Math.max(
    0,
    Math.round((Date.now() - new Date(iso).getTime()) / 60000),
  );
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}
