"use client";

// S19: my tickets. Questions the AI passed to support (or that I sent myself), their status and the answer.

import { LifeBuoy, Send, Ticket } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import {
  ago,
  REASON_LABEL,
  StatusPill,
  Tag,
  type TicketRow,
} from "@/components/tickets";
import { Alert, Button, Card, EmptyState, SkeletonCard } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";

function MyTickets() {
  const [tickets, setTickets] = useState<TicketRow[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [subject, setSubject] = useState("");
  const [details, setDetails] = useState("");
  const [sent, setSent] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setTickets(await apiFetch<TicketRow[]>("/tickets/mine"));
    } catch (e) {
      setError(
        e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)),
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function send() {
    try {
      const t = await apiFetch<TicketRow>("/tickets", {
        method: "POST",
        body: JSON.stringify({ subject, details }),
      });
      setSent(t.id);
      setSubject("");
      setDetails("");
      load();
    } catch (e) {
      setError(
        e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)),
      );
    }
  }

  return (
    <div className="space-y-6">
      {error && <Alert title={error.message} detail={error.detail} />}
      <Card
        title="My tickets"
        subtitle="Questions a person is answering for you. Most are opened for you by the chat."
        icon={<Ticket className="h-4 w-4" />}
      >
        {!tickets ? (
          <SkeletonCard lines={4} />
        ) : tickets.length === 0 ? (
          <EmptyState
            title="No tickets"
            hint="When the chat can't answer, isn't sure, or you press 👎, the question comes here with support's answer."
          />
        ) : (
          <div className="divide-y divide-line">
            {tickets.map((t) => (
              <div key={t.id} className="space-y-2 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill status={t.status} />
                  <span className="font-mono text-xs text-faint">#{t.id}</span>
                  <Tag>{REASON_LABEL[t.reason] ?? t.reason}</Tag>
                  {t.course_code && <Tag>{t.course_code}</Tag>}
                  <span className="ml-auto text-xs text-faint">
                    {ago(t.created_at)}
                  </span>
                </div>
                <p className="whitespace-pre-wrap text-sm text-fg">
                  {t.subject}
                </p>
                {t.resolution ? (
                  <div className="rounded-xl border border-ok/30 bg-ok-soft/40 p-3">
                    <p className="text-xs font-medium text-ok">
                      Answer from support
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-fg">
                      {t.resolution}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-muted">
                    {t.status === "in_progress"
                      ? "Someone is working on it."
                      : "Waiting for the support team."}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card
        title="Ask support"
        subtitle="For anything the chat can't help with: your account, a payment, a certificate."
        icon={<LifeBuoy className="h-4 w-4" />}
      >
        <div className="space-y-2">
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="What do you need help with?"
            className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg"
          />
          <textarea
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            placeholder="Details (optional)"
            rows={3}
            className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-fg"
          />
          <div className="flex items-center gap-3">
            <Button onClick={send} disabled={subject.trim().length < 5}>
              <Send className="h-4 w-4" /> Send
            </Button>
            {sent && (
              <span className="text-sm text-ok">Sent as ticket #{sent}.</span>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <PortalShell role="student" title="My tickets" showRoadmap={false}>
      {() => <MyTickets />}
    </PortalShell>
  );
}
