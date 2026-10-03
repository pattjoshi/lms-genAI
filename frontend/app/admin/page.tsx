"use client";

import { Activity, ChartColumn } from "lucide-react";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { Alert, Card, EmptyState, ProgressBar, SkeletonCard, Stat } from "@/components/ui";
import { useApi } from "@/components/useApi";

type Summary = {
  users_by_role: Record<string, number>;
  enrollments: number;
  revenue_inr_30d: number;
  failed_payments_30d: number;
  ai_today: { calls: number; errors: number; cost_usd: number; budget_usd: number };
  recent_ai_calls: {
    at: string;
    feature: string;
    model: string;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    latency_ms: number;
    attempts: number;
    status: string;
    error_code: string | null;
  }[];
};

function AdminHome() {
  const { data, error } = useApi<Summary>("/portal/admin/summary");
  if (error) return <Alert title={error.message} detail={error.detail} />;
  if (!data)
    return (
      <>
        <SkeletonCard lines={2} />
        <SkeletonCard lines={5} />
      </>
    );

  const usedPct = Math.min(100, (data.ai_today.cost_usd / Math.max(data.ai_today.budget_usd, 1e-9)) * 100);
  const budgetTone = usedPct >= 80 ? "bg-bad" : usedPct >= 50 ? "bg-warn" : "bg-ok";

  return (
    <>
      <Card title="LMS at a glance" icon={<ChartColumn className="h-4 w-4" />}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Students" value={data.users_by_role.student ?? 0} />
          <Stat label="Enrollments" value={data.enrollments} />
          <Stat label="Revenue (30 days)" value={`₹${data.revenue_inr_30d.toLocaleString("en-IN")}`} />
          <Stat label="Failed payments (30 days)" value={data.failed_payments_30d} />
        </div>
      </Card>

      <Card
        title="AI usage today"
        subtitle="From the llm_usage table. Refresh after an AI call to see it here."
        icon={<Activity className="h-4 w-4" />}
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Calls" value={data.ai_today.calls} />
          <Stat label="Errors" value={data.ai_today.errors} />
          <Stat
            label="Cost / daily budget"
            mono
            value={`$${data.ai_today.cost_usd.toFixed(4)} / $${data.ai_today.budget_usd.toFixed(2)}`}
          />
        </div>
        <div className="mt-4 flex items-center gap-3">
          <div className="flex-1">
            <ProgressBar value={usedPct} tone={budgetTone} />
          </div>
          <span className="font-mono text-xs text-muted">{usedPct.toFixed(1)}% used</span>
        </div>

        <div className="mt-5">
          {data.recent_ai_calls.length === 0 ? (
            <EmptyState title="No AI calls yet" hint="Use the AI connection test below." />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-line">
              <table className="w-full text-left text-sm">
                <thead className="bg-surface-2/70 text-xs text-muted">
                  <tr>
                    {["Time", "Feature", "Tokens in/out", "Cost", "Latency", "Attempts", "Status"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.recent_ai_calls.map((r, i) => (
                    <tr key={i} className="text-fg">
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                        {new Date(r.at).toLocaleTimeString()}
                      </td>
                      <td className="px-3 py-2">{r.feature}</td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {r.input_tokens} / {r.output_tokens}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">${r.cost_usd.toFixed(6)}</td>
                      <td className="px-3 py-2 font-mono text-xs">{r.latency_ms} ms</td>
                      <td className="px-3 py-2 font-mono text-xs">{r.attempts}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            r.status === "error" ? "bg-bad-soft text-bad" : "bg-ok-soft text-ok"
                          }`}
                        >
                          {r.status === "error" ? r.error_code : "ok"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </>
  );
}

export default function AdminPage() {
  return (
    <PortalShell role="admin">
      {() => (
        <>
          <AdminHome />
          <AiHelloCard />
          <PermissionTestCard />
        </>
      )}
    </PortalShell>
  );
}
