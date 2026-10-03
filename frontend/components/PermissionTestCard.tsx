"use client";

// Same request from every portal: "list all students". The backend answers
// differently per role — the permission matrix in action.

import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { Alert, Button, Card, Chip } from "./ui";

type StudentList = {
  scope: string;
  total: number;
  students: { id: number; full_name: string; email: string; city: string }[];
};

const EXPECTED = [
  ["Student", "refused"],
  ["Teacher", "own course only"],
  ["Admin", "everyone"],
  ["Support", "refused until tickets"],
];

export function PermissionTestCard() {
  const [data, setData] = useState<StudentList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    setData(null);
    try {
      setData(await apiFetch<StudentList>("/data/students?limit=10"));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Permission test: “list all students”"
      subtitle="Same request from every portal, different answer per role"
      icon={<ShieldCheck className="h-4 w-4" />}
      action={
        <Button variant="ghost" onClick={run} disabled={busy}>
          {busy ? "Running…" : "Run request"}
        </Button>
      }
    >
      <div className="flex flex-wrap gap-1.5">
        {EXPECTED.map(([role, result]) => (
          <Chip key={role}>
            <span className="font-medium text-fg">{role}</span> → {result}
          </Chip>
        ))}
      </div>

      {error && (
        <div className="mt-4">
          <Alert title={`HTTP ${error.status}: ${error.message}`} />
        </div>
      )}

      {data && (
        <div className="mt-4">
          <Alert
            tone="ok"
            title={`Allowed with scope “${data.scope}”: ${data.total} students (showing ${data.students.length})`}
          />
          <ul className="mt-3 divide-y divide-line">
            {data.students.map((s) => (
              <li key={s.id} className="flex justify-between gap-3 py-2 text-sm">
                <span className="text-fg">{s.full_name}</span>
                <span className="text-muted">{s.city}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
