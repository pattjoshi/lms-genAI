"use client";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { Card, ErrorBox, Loading, Stat } from "@/components/ui";
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
  if (error) return <ErrorBox message={error.message} detail={error.detail} />;
  if (!data) return <Loading />;

  return (
    <>
      {data.courses.map((c) => (
        <Card key={c.code} title={`${c.title} (${c.code})`} subtitle="Only your own course is visible to you">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Enrolled" value={c.enrolled} />
            <Stat label="Active" value={c.active} />
            <Stat label="Completed" value={c.completed} />
            <Stat label="Dropped" value={c.dropped} />
          </div>
          <p className="mt-4 text-sm font-medium text-slate-700">Hardest topics (lowest average quiz score)</p>
          <ul className="mt-2 space-y-1 text-sm">
            {c.hardest_topics.map((t) => (
              <li key={t.topic} className="flex justify-between">
                <span>{t.topic}</span>
                <span className={t.avg_score < 50 ? "font-medium text-red-600" : "text-slate-600"}>{t.avg_score}%</span>
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
