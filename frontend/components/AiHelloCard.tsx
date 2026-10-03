"use client";

// Phase 0's first LLM call. Shows what every call costs: tokens, $, latency, retries.

import { useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { Card, ErrorBox, Stat } from "./ui";

type HelloResult = {
  reply: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  attempts: number;
};

export function AiHelloCard() {
  const [message, setMessage] = useState("Hi! What can you help me with?");
  const [result, setResult] = useState<HelloResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      setResult(await apiFetch<HelloResult>("/ai/hello", { method: "POST", body: JSON.stringify({ message }) }));
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="AI connection test" subtitle="One LLM call through the full pipeline: budget check → retry → usage log → Langfuse trace">
      <div className="flex gap-2">
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !busy && send()}
          maxLength={1000}
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
        />
        <button
          onClick={send}
          disabled={busy || !message.trim()}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {busy ? "Asking…" : "Send"}
        </button>
      </div>

      {error && (
        <div className="mt-3">
          <ErrorBox message={`${error.message} (${error.code})`} detail={error.detail} />
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-3">
          <p className="rounded-lg bg-indigo-50 p-3 text-sm text-slate-800">{result.reply}</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Stat label="Model" value={<span className="text-sm">{result.model}</span>} />
            <Stat label="Tokens in / out" value={`${result.input_tokens} / ${result.output_tokens}`} />
            <Stat label="Cost" value={`$${result.cost_usd.toFixed(6)}`} />
            <Stat label="Latency" value={`${result.latency_ms} ms`} />
            <Stat label="Attempts" value={result.attempts} hint={result.attempts > 1 ? "retried" : "no retry"} />
          </div>
        </div>
      )}
    </Card>
  );
}
