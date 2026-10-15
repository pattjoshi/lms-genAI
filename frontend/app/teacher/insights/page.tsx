"use client";

// T13, T14: what students ask, grouped by meaning, and the questions the course material can't answer.
// Students are counted, never named.

import { MessageCircleQuestion, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { PortalShell } from "@/components/PortalShell";
import { ago, Tag } from "@/components/tickets";
import { Alert, Card, Chip, EmptyState, SkeletonCard } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";

type Group = {
  label: string;
  count: number;
  students: number;
  course_code: string;
  examples: string[];
  unanswered: number;
  low_confidence: number;
  thumbs_down: number;
  last_asked: string;
  ticket_status: string | null;
};

type Insights = {
  days: number;
  courses: string[];
  questions: number;
  threshold: number;
  embedded_now: number;
  embed_cost_usd: number;
  most_asked: Group[];
  gaps: Group[];
};

function GroupList({ groups, gaps }: { groups: Group[]; gaps?: boolean }) {
  if (groups.length === 0)
    return (
      <EmptyState
        title={gaps ? "No gaps" : "No questions yet"}
        hint={
          gaps
            ? "Every question in this period was answered with confidence."
            : "Questions students ask in the chat show up here."
        }
      />
    );
  const top = groups[0].count;
  return (
    <div className="space-y-3">
      {groups.map((g, i) => (
        <details key={i} className="group rounded-xl border border-line p-3">
          <summary className="flex cursor-pointer list-none items-start gap-3">
            <span className="w-8 shrink-0 text-right font-display text-lg font-semibold text-fg">
              {g.count}
            </span>
            <div className="min-w-0 flex-1 space-y-1.5">
              <p className="text-sm text-fg">{g.label}</p>
              <div className="h-1.5 rounded-full bg-surface-2">
                <div
                  className={`h-1.5 rounded-full ${gaps ? "bg-warn" : "bg-brand"}`}
                  style={{ width: `${Math.max(6, (g.count / top) * 100)}%` }}
                />
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Tag>{g.course_code}</Tag>
                <Tag>
                  {g.students} student{g.students === 1 ? "" : "s"}
                </Tag>
                {g.unanswered > 0 && <Tag>{g.unanswered} not answered</Tag>}
                {g.low_confidence > 0 && (
                  <Tag>{g.low_confidence} low confidence</Tag>
                )}
                {g.thumbs_down > 0 && <Tag>{g.thumbs_down} 👎</Tag>}
                {g.ticket_status && (
                  <Tag>support: {g.ticket_status.replace("_", " ")}</Tag>
                )}
                <span className="text-[11px] text-faint">
                  last {ago(g.last_asked)}
                </span>
              </div>
            </div>
          </summary>
          {g.examples.length > 1 && (
            <ul className="mt-2 space-y-0.5 pl-11 text-xs text-muted">
              {g.examples.map((e) => (
                <li key={e}>“{e}”</li>
              ))}
            </ul>
          )}
        </details>
      ))}
    </div>
  );
}

function InsightsView() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    setData(null);
    apiFetch<Insights>(`/insights?days=${days}`)
      .then(setData)
      .catch((e) =>
        setError(
          e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)),
        ),
      );
  }, [days]);

  if (error) return <Alert title={error.message} detail={error.detail} />;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
        <span>Last</span>
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${days === d ? "border-brand bg-brand-soft text-brand-ink" : "border-line hover:text-fg"}`}
          >
            {d} days
          </button>
        ))}
        {data && (
          <span className="ml-auto flex flex-wrap gap-1.5">
            <Chip>{data.questions} questions</Chip>
            <Chip>{data.courses.join(", ") || "no courses"}</Chip>
            <Chip mono>grouped at cosine ≥ {data.threshold}</Chip>
            {data.embedded_now > 0 && (
              <Chip mono>
                embedded {data.embedded_now} now, $
                {data.embed_cost_usd.toFixed(6)}
              </Chip>
            )}
          </span>
        )}
      </div>
      {!data ? (
        <SkeletonCard lines={6} />
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          <Card
            title="Most asked doubts"
            subtitle="Questions that mean the same thing are counted together, whatever the wording."
            icon={<MessageCircleQuestion className="h-4 w-4" />}
          >
            <GroupList groups={data.most_asked} />
          </Card>
          <Card
            title="Content gaps"
            subtitle="What the AI couldn't answer from your material, wasn't sure about, or got a 👎. Each is a page worth adding."
            icon={<TriangleAlert className="h-4 w-4" />}
          >
            <GroupList groups={data.gaps} gaps />
          </Card>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <PortalShell role="teacher" title="Doubt insights" showRoadmap={false}>
      {() => <InsightsView />}
    </PortalShell>
  );
}
