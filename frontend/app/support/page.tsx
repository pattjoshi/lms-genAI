"use client";

import { ArrowRight, Inbox } from "lucide-react";
import Link from "next/link";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { ago, REASON_LABEL } from "@/components/tickets";
import { Alert, Card, SkeletonCard, Stat } from "@/components/ui";
import { useApi } from "@/components/useApi";

type Summary = {
  by_status: Record<string, number>;
  open_by_reason: Record<string, number>;
  oldest_open_at: string | null;
  kb_entries: number;
};

function SupportHome() {
  const { data, error } = useApi<Summary>("/portal/support/summary");
  if (error) return <Alert title={error.message} detail={error.detail} />;
  if (!data) return <SkeletonCard />;
  return (
    <Card
      title="Ticket queue"
      subtitle="Support sees a student's data only through an open ticket"
      icon={<Inbox className="h-4 w-4" />}
      action={
        <Link
          href="/support/tickets"
          className="inline-flex items-center gap-1 text-sm text-brand-ink hover:underline"
        >
          Open the queue <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      }
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="Open"
          value={data.by_status.open}
          hint={
            data.oldest_open_at
              ? `oldest ${ago(data.oldest_open_at)}`
              : undefined
          }
        />
        <Stat label="In progress" value={data.by_status.in_progress} />
        <Stat label="Resolved" value={data.by_status.resolved} />
        <Stat
          label="Knowledge base"
          value={data.kb_entries}
          hint="verified answers"
        />
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted">
        {Object.entries(data.open_by_reason)
          .filter(([, n]) => n > 0)
          .map(([r, n]) => (
            <span
              key={r}
              className="rounded-full border border-line px-2.5 py-0.5"
            >
              {REASON_LABEL[r] ?? r}:{" "}
              <span className="font-medium text-fg">{n}</span>
            </span>
          ))}
      </div>
    </Card>
  );
}

export default function SupportPage() {
  return (
    <PortalShell role="support">
      {() => (
        <>
          <SupportHome />
          <PermissionTestCard />
          <AiHelloCard />
        </>
      )}
    </PortalShell>
  );
}
