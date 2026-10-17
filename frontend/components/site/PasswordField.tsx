"use client";

import { Eye, EyeOff } from "lucide-react";
import { useId, useState } from "react";

import { inputClass } from "./AuthShell";

/** A rough strength score for the meter (the backend makes the real decision). */
function strength(pw: string): { score: number; label: string } {
  if (!pw) return { score: 0, label: "" };
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw) || /[^A-Za-z0-9]/.test(pw)) score++;
  if (pw.length < 8) score = Math.min(score, 1);
  return { score, label: ["Too short", "Weak", "Okay", "Good", "Strong"][score] };
}

const BAR = ["bg-bad", "bg-bad", "bg-warn", "bg-ok", "bg-ok"];

export function PasswordField({
  value,
  onChange,
  autoComplete,
  label = "Password",
  showStrength = false,
  minLength = 8,
  error,
}: {
  value: string;
  onChange: (v: string) => void;
  autoComplete: "current-password" | "new-password";
  label?: string;
  showStrength?: boolean;
  minLength?: number;
  error?: string | null;
}) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const s = strength(value);
  const hintId = `${id}-hint`;

  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-fg">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          required
          minLength={showStrength ? minLength : undefined}
          maxLength={128}
          aria-invalid={error ? true : undefined}
          aria-describedby={showStrength || error ? hintId : undefined}
          className={`${inputClass} pr-12`}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg"
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
      {showStrength && (
        <div id={hintId} className="mt-2">
          <div className="flex gap-1" aria-hidden>
            {[1, 2, 3, 4].map((i) => (
              <span key={i} className={`h-1 flex-1 rounded-full ${i <= s.score ? BAR[s.score] : "bg-line"}`} />
            ))}
          </div>
          <p className="mt-1.5 text-xs text-muted">
            {value ? `${s.label}. ` : ""}At least {minLength} characters. A short sentence works well.
          </p>
        </div>
      )}
      {error && !showStrength && (
        <p id={hintId} className="mt-1.5 text-xs text-bad">
          {error}
        </p>
      )}
    </div>
  );
}
