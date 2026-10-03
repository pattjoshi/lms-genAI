"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { applyTheme, getThemeChoice, setThemeChoice, type ThemeChoice } from "@/lib/theme";

const OPTIONS: { value: ThemeChoice; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
];

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice | null>(null);

  useEffect(() => {
    const current = getThemeChoice();
    setChoice(current);
    // While on "System", follow the OS live when it switches light/dark.
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => getThemeChoice() === "system" && applyTheme("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  return (
    <div role="radiogroup" aria-label="Theme" className="flex rounded-xl border border-line bg-surface-2 p-0.5">
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          role="radio"
          aria-checked={choice === value}
          title={label}
          onClick={() => {
            setThemeChoice(value);
            setChoice(value);
          }}
          className={`flex h-7 w-8 items-center justify-center rounded-lg transition-colors ${
            choice === value ? "bg-surface text-fg shadow-card" : "text-faint hover:text-fg"
          }`}
        >
          <Icon className="h-4 w-4" />
          <span className="sr-only">{label}</span>
        </button>
      ))}
    </div>
  );
}
