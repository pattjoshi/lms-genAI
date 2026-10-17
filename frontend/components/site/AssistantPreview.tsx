import { BadgeCheck, FileText, Route, Sparkles } from "lucide-react";

/** A static picture of the chat (not a live demo), drawn with HTML so it stays sharp and themed. */
export function AssistantPreview() {
  return (
    <div className="relative mx-auto w-full max-w-md lg:max-w-none" aria-hidden>
      <div className="absolute -inset-6 -z-10 rounded-[2.5rem] bg-gradient-to-br from-brand/25 via-transparent to-[#22d3ee]/20 blur-2xl" />
      <div className="rounded-3xl border border-line bg-surface p-4 shadow-[0_30px_80px_-20px_rgba(40,30,120,0.35)] sm:p-5">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-soft text-brand-ink">
              <Sparkles className="h-4 w-4" />
            </span>
            <div>
              <p className="text-sm font-semibold text-fg">AI tutor</p>
              <p className="text-[11px] text-muted">Deep Learning · DL301</p>
            </div>
          </div>
          <span className="rounded-full bg-ok-soft px-2 py-0.5 text-[11px] font-medium text-ok">Online</span>
        </div>

        <div className="space-y-3 py-4 text-sm">
          <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-brand px-3.5 py-2.5 text-brand-fg">
            Why does my network stop learning when I add more layers?
          </div>
          <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-line bg-surface-2/70 px-3.5 py-2.5 text-fg">
            That&apos;s the <strong>vanishing gradient</strong> problem. Each layer multiplies the gradient by a small
            number, so early layers barely change. ReLU activations and batch normalisation keep it in range.
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              <span className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-0.5 text-[11px] text-muted">
                <FileText className="h-3 w-3" /> week4-backprop.pdf · p. 12
              </span>
              <span className="inline-flex items-center gap-1 rounded-md bg-ok-soft px-2 py-0.5 text-[11px] font-medium text-ok">
                <BadgeCheck className="h-3 w-3" /> High confidence
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 rounded-xl border border-line bg-surface-2/60 px-3 py-2.5 text-sm text-faint">
          Ask a follow-up…
          <span className="ml-auto rounded-lg bg-brand px-2.5 py-1 text-xs font-semibold text-brand-fg">Send</span>
        </div>
      </div>

      <div className="absolute -bottom-6 -left-4 hidden w-60 rounded-2xl border border-line bg-surface p-3.5 shadow-card sm:block lg:-left-10">
        <p className="flex items-center gap-1.5 text-xs font-semibold text-fg">
          <Route className="h-3.5 w-3.5 text-brand-ink" /> Your path to Backprop
        </p>
        <ol className="mt-2 space-y-1.5 text-xs">
          {[
            ["Derivatives", true],
            ["Chain rule", true],
            ["Gradient descent", false],
          ].map(([step, done]) => (
            <li key={String(step)} className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${done ? "bg-ok" : "bg-brand"}`} />
              <span className={done ? "text-muted line-through" : "font-medium text-fg"}>{step}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
