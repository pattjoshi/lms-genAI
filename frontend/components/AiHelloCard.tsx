"use client";

// Phase 0's first LLM call, shown as a mini chat. Under each AI reply: what the
// call cost — model, tokens, $, latency and how many attempts (retries) it took.

import { Bot, Send, Sparkles } from "lucide-react";
import { useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { Alert, Button, Card, Chip } from "./ui";

type HelloResult = {
  reply: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  attempts: number;
};

type Turn = { question: string; result?: HelloResult; error?: ApiError };

export function AiHelloCard() {
  const [message, setMessage] = useState("Hi! What can you help me with?");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  async function send() {
    const question = message.trim();
    if (!question || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await apiFetch<HelloResult>("/ai/hello", {
        method: "POST",
        body: JSON.stringify({ message: question }),
      });
      setTurns((t) => [...t, { question, result }]);
    } catch (e) {
      const error = e instanceof ApiError ? e : new ApiError(0, "unknown", String(e));
      setTurns((t) => [...t, { question, error }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="AI connection test"
      subtitle="One LLM call through the full pipeline: budget check → retry → usage log → Langfuse trace"
      icon={<Sparkles className="h-4 w-4" />}
    >
      <div className="space-y-4">
        {turns.length === 0 && !busy && (
          <p className="rounded-xl bg-surface-2/60 px-4 py-3 text-sm text-muted">
            Send a message to make your first LLM call. Each reply shows its tokens, cost and latency.
          </p>
        )}

        {turns.map((t, i) => (
          <div key={i} className="space-y-2">
            <div className="flex justify-end">
              <p className="max-w-[80%] rounded-2xl rounded-br-md bg-brand px-4 py-2 text-sm text-brand-fg">
                {t.question}
              </p>
            </div>
            {t.result && (
              <div className="flex gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-ink">
                  <Bot className="h-4 w-4" />
                </span>
                <div className="min-w-0 space-y-2">
                  <p className="rounded-2xl rounded-tl-md border border-line bg-surface-2/60 px-4 py-2 text-sm text-fg">
                    {t.result.reply}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    <Chip mono>{t.result.model}</Chip>
                    <Chip mono>
                      {t.result.input_tokens} in / {t.result.output_tokens} out
                    </Chip>
                    <Chip mono>${t.result.cost_usd.toFixed(6)}</Chip>
                    <Chip mono>{t.result.latency_ms} ms</Chip>
                    <Chip mono>
                      {t.result.attempts} {t.result.attempts === 1 ? "attempt" : "attempts (retried)"}
                    </Chip>
                  </div>
                </div>
              </div>
            )}
            {t.error && <Alert title={`${t.error.message} (${t.error.code})`} detail={t.error.detail} />}
          </div>
        ))}

        {busy && (
          <div className="flex items-center gap-2.5 text-sm text-muted">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-soft text-brand-ink">
              <Bot className="h-4 w-4 animate-pulse" />
            </span>
            Thinking…
          </div>
        )}

        <div className="flex gap-2">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            maxLength={1000}
            placeholder="Type a message…"
            className="flex-1 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm text-fg placeholder:text-faint focus:border-brand focus:outline-none"
          />
          <Button onClick={send} disabled={busy || !message.trim()} aria-label="Send">
            <Send className="h-4 w-4" />
            <span className="hidden sm:inline">Send</span>
          </Button>
        </div>
      </div>
    </Card>
  );
}
