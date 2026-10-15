"use client";

// P5: the knowledge base. Answers support saved from resolved tickets; the AI searches them next to the
// course material. Withdrawing an entry stops the AI using it (the row is kept for the record).

import { ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { ago, Tag } from "@/components/tickets";
import { Alert, Card, EmptyState, SkeletonCard } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";

type Entry = {
  id: number;
  course_code: string;
  question: string;
  answer: string;
  ticket_id: number | null;
  created_by: string;
  created_at: string | null;
  active: boolean;
};

function KnowledgeBase() {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    try {
      setEntries(await apiFetch<Entry[]>("/kb"));
    } catch (e) {
      setError(
        e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)),
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function withdraw(id: number) {
    await apiFetch(`/kb/${id}`, { method: "DELETE" });
    load();
  }

  if (error) return <Alert title={error.message} detail={error.detail} />;
  return (
    <Card
      title="Knowledge base"
      subtitle="Verified answers the AI reuses when someone in the course asks the same question."
      icon={<ShieldCheck className="h-4 w-4" />}
    >
      {!entries ? (
        <SkeletonCard lines={4} />
      ) : entries.length === 0 ? (
        <EmptyState
          title="Empty"
          hint="Resolve a course question with “Save to knowledge base” ticked."
        />
      ) : (
        <div className="divide-y divide-line">
          {entries.map((e) => (
            <div key={e.id} className="space-y-1.5 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <Tag>{e.course_code}</Tag>
                {e.ticket_id && (
                  <a
                    href={`/support/tickets?id=${e.ticket_id}`}
                    className="font-mono text-xs text-faint hover:underline"
                  >
                    ticket #{e.ticket_id}
                  </a>
                )}
                <span className="text-xs text-faint">
                  {e.created_by} · {ago(e.created_at)}
                </span>
                <button
                  onClick={() => withdraw(e.id)}
                  className="ml-auto text-xs text-bad hover:underline"
                >
                  Withdraw
                </button>
              </div>
              <p className="text-sm font-medium text-fg">{e.question}</p>
              <p className="whitespace-pre-wrap text-sm text-muted">
                {e.answer}
              </p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function Page() {
  return (
    <PortalShell role="support" title="Knowledge base" showRoadmap={false}>
      {() => <KnowledgeBase />}
    </PortalShell>
  );
}
