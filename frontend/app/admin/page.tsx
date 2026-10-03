"use client";

import { AiHelloCard } from "@/components/AiHelloCard";
import { PermissionTestCard } from "@/components/PermissionTestCard";
import { PortalShell } from "@/components/PortalShell";
import { Card, ErrorBox, Loading, Stat } from "@/components/ui";
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
  if (error) return <ErrorBox message={error.message} detail={error.detail} />;
  if (!data) return <Loading />;

  const usedPct = Math.min(100, (data.ai_today.cost_usd / Math.max(data.ai_today.budget_usd, 1e-9)) * 100);

  return (
    <>
      <Card title="LMS at a glance">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Students" value={data.users_by_role.student ?? 0} />
          <Stat label="Enrollments" value={data.enrollments} />
          <Stat label="Revenue (30 days)" value={`₹${data.revenue_inr_30d.toLocaleString("en-IN")}`} />
          <Stat label="Failed payments (30 days)" value={data.failed_payments_30d} />
        </div>
      </Card>

      <Card title="AI usage today" subtitle="From the llm_usage table. Refresh the page after an AI call to see it here.">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Stat label="Calls" value={data.ai_today.calls} />
          <Stat label="Errors" value={data.ai_today.errors} />
          <Stat
            label="Cost / daily budget"
            value={`$${data.ai_today.cost_usd.toFixed(4)} / $${data.ai_today.budget_usd.toFixed(2)}`}
          />
        </div>
        <div className="mt-3 h-2 rounded-full bg-slate-100">
          <div
            className={`h-2 rounded-full ${usedPct >= 80 ? "bg-red-500" : "bg-emerald-500"}`}
            style={{ width: `${usedPct}%` }}
          />
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2">Time</th>
                <th>Feature</th>
                <th>Tokens in/out</th>
                <th>Cost</th>
                <th>Latency</th>
                <th>Attempts</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.recent_ai_calls.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-3 text-slate-500">
                    No AI calls yet. Use the AI connection test below.
                  </td>
                </tr>
              )}
              {data.recent_ai_calls.map((r, i) => (
                <tr key={i}>
                  <td className="py-1.5">{new Date(r.at).toLocaleTimeString()}</td>
                  <td>{r.feature}</td>
                  <td>
                    {r.input_tokens} / {r.output_tokens}
                  </td>
                  <td>${r.cost_usd.toFixed(6)}</td>
                  <td>{r.latency_ms} ms</td>
                  <td>{r.attempts}</td>
                  <td className={r.status === "error" ? "text-red-600" : "text-emerald-700"}>
                    {r.status === "error" ? r.error_code : "ok"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
