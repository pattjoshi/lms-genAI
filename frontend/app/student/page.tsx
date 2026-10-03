"use client";

import { BookOpen, TrendingDown } from "lucide-react";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { Alert, Card, EmptyState, ProgressBar, ScoreText, SkeletonCard } from "@/components/ui";
import { useApi } from "@/components/useApi";

type Summary = {
  courses: { code: string; title: string; status: string; progress_pct: number }[];
  weakest_topics: { topic: string; course: string; avg_score: number }[];
};

const STATUS_STYLE: Record<string, string> = {
  active: "bg-brand-soft text-brand-ink",
  completed: "bg-ok-soft text-ok",
  dropped: "bg-surface-2 text-muted",
};

function StudentHome() {
  const { data, error } = useApi<Summary>("/portal/student/summary");
  if (error) return <Alert title={error.message} detail={error.detail} />;
  if (!data)
    return (
      <div className="grid gap-5 md:grid-cols-2">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <Card title="My courses" icon={<BookOpen className="h-4 w-4" />}>
        {data.courses.length === 0 ? (
          <EmptyState title="No courses yet" />
        ) : (
          <ul className="space-y-4">
            {data.courses.map((c) => (
              <li key={c.code}>
                <div className="mb-1.5 flex items-center justify-between gap-2 text-sm">
                  <span className="font-medium text-fg">{c.title}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs capitalize ${STATUS_STYLE[c.status] ?? ""}`}>
                    {c.status}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex-1">
                    <ProgressBar value={c.progress_pct} tone={c.status === "completed" ? "bg-ok" : "bg-brand"} />
                  </div>
                  <span className="w-10 text-right font-mono text-xs text-muted">{c.progress_pct}%</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title="My weakest topics"
        subtitle="From my quiz scores. Phase 4 turns this into the assistant's memory."
        icon={<TrendingDown className="h-4 w-4" />}
      >
        {data.weakest_topics.length === 0 ? (
          <EmptyState title="No quiz attempts yet" />
        ) : (
          <ul className="divide-y divide-line">
            {data.weakest_topics.map((t) => (
              <li key={t.topic} className="flex items-center justify-between py-2.5 text-sm">
                <span className="text-fg">
                  {t.topic} <span className="font-mono text-xs text-faint">{t.course}</span>
                </span>
                <ScoreText score={t.avg_score} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function StudentPage() {
  return (
    <PortalShell role="student">
      {() => (
        <>
          <StudentHome />
          <AiHelloCard />
          <PermissionTestCard />
        </>
      )}
    </PortalShell>
  );
}
