"use client";

// Same request from every portal: "list all students". The backend answers
// differently per role — the permission matrix in action.

import { useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { Card, ErrorBox } from "./ui";

type StudentList = {
  scope: string;
  total: number;
  students: { id: number; full_name: string; email: string; city: string }[];
};

export function PermissionTestCard() {
  const [data, setData] = useState<StudentList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  async function run() {
    setError(null);
    setData(null);
    try {
      setData(await apiFetch<StudentList>("/data/students?limit=10"));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    }
  }

  return (
    <Card
      title="Permission test: “list all students”"
      subtitle="Student → refused · Teacher → only own course's students · Admin → everyone · Support → refused until tickets exist"
    >
      <button
        onClick={run}
        className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
      >
        Run request
      </button>

      {error && (
        <div className="mt-3">
          <ErrorBox message={`HTTP ${error.status}: ${error.message}`} />
        </div>
      )}

      {data && (
        <div className="mt-3 text-sm">
          <p className="text-slate-600">
            Scope <code className="rounded bg-slate-100 px-1">{data.scope}</code> · {data.total} students (showing{" "}
            {data.students.length})
          </p>
          <ul className="mt-2 divide-y divide-slate-100">
            {data.students.map((s) => (
              <li key={s.id} className="flex justify-between py-1.5">
                <span className="text-slate-800">{s.full_name}</span>
                <span className="text-slate-500">{s.city}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
