"use client";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { Card, ErrorBox, Loading } from "@/components/ui";
import { useApi } from "@/components/useApi";

type Summary = {
  courses: { code: string; title: string; status: string; progress_pct: number }[];
  weakest_topics: { topic: string; course: string; avg_score: number }[];
};

function StudentHome() {
  const { data, error } = useApi<Summary>("/portal/student/summary");
  if (error) return <ErrorBox message={error.message} detail={error.detail} />;
  if (!data) return <Loading />;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card title="My courses">
        <ul className="space-y-3">
          {data.courses.map((c) => (
            <li key={c.code}>
              <div className="flex justify-between text-sm">
                <span className="font-medium">{c.title}</span>
                <span className="text-slate-500">{c.status}</span>
              </div>
              <div className="mt-1 h-2 rounded-full bg-slate-100">
                <div className="h-2 rounded-full bg-indigo-500" style={{ width: `${c.progress_pct}%` }} />
              </div>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="My weakest topics" subtitle="From my quiz scores. Phase 4 turns this into the assistant's memory.">
        <ul className="space-y-2 text-sm">
          {data.weakest_topics.map((t) => (
            <li key={t.topic} className="flex justify-between">
              <span>
                {t.topic} <span className="text-slate-400">· {t.course}</span>
              </span>
              <span className={t.avg_score < 50 ? "font-medium text-red-600" : "text-slate-600"}>{t.avg_score}%</span>
            </li>
          ))}
        </ul>
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
