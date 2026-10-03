"use client";

import { BookOpen } from "lucide-react";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { Alert, Card, ScoreText, SkeletonCard, Stat } from "@/components/ui";
import { useApi } from "@/components/useApi";

type Summary = {
  courses: {
    code: string;
    title: string;
    enrolled: number;
    active: number;
    completed: number;
    dropped: number;
    hardest_topics: { topic: string; avg_score: number }[];
  }[];
};

function TeacherHome() {
  const { data, error } = useApi<Summary>("/portal/teacher/summary");
  if (error) return <Alert title={error.message} detail={error.detail} />;
  if (!data) return <SkeletonCard lines={5} />;

  return (
    <>
      {data.courses.map((c) => (
        <Card
          key={c.code}
          title={c.title}
          subtitle={`${c.code} · only your own course is visible to you`}
          icon={<BookOpen className="h-4 w-4" />}
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Enrolled" value={c.enrolled} />
            <Stat label="Active" value={c.active} />
            <Stat label="Completed" value={c.completed} />
            <Stat label="Dropped" value={c.dropped} />
          </div>
          <p className="mt-5 text-sm font-medium text-fg">Hardest topics</p>
          <p className="text-xs text-muted">Lowest average quiz score. Phase 5 adds the doubts students ask about them.</p>
          <ul className="mt-2 divide-y divide-line">
            {c.hardest_topics.map((t) => (
              <li key={t.topic} className="flex items-center justify-between py-2.5 text-sm">
                <span className="text-fg">{t.topic}</span>
                <ScoreText score={t.avg_score} />
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </>
  );
}

export default function TeacherPage() {
  return (
    <PortalShell role="teacher">
      {() => (
        <>
          <TeacherHome />
          <PermissionTestCard />
          <AiHelloCard />
        </>
      )}
    </PortalShell>
  );
}
