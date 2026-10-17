"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

type Plan = {
  name: string;
  blurb: string;
  monthly: number | null; // null = talk to us
  cta: { label: string; href: string };
  features: string[];
  highlight?: boolean;
};

const PLANS: Plan[] = [
  {
    name: "Free",
    blurb: "Look around and try the AI tutor.",
    monthly: 0,
    cta: { label: "Create a free account", href: "/signup" },
    features: ["Browse every course outline", "Sample lessons", "AI tutor on sample lessons", "Community support"],
  },
  {
    name: "Plus",
    blurb: "Everything you need to learn and get certified.",
    monthly: 799,
    cta: { label: "Start Plus", href: "/signup?plan=plus" },
    highlight: true,
    features: [
      "Every course in the catalogue",
      "Unlimited questions to the AI tutor, with sources",
      "Personal learning paths and practice quizzes",
      "Help from the support team when the AI isn't sure",
      "Use your courses from Claude Desktop or Cursor",
    ],
  },
  {
    name: "Teams",
    blurb: "For colleges, bootcamps and companies.",
    monthly: null,
    cta: { label: "Talk to us", href: "/signup?plan=teams" },
    features: [
      "Everything in Plus, for every seat",
      "Upload your own material; the AI answers from it",
      "Instructor insights: most asked doubts and content gaps",
      "Admin roles, usage and cost dashboards",
      "Ask your learning data in plain English",
    ],
  },
];

const price = (n: number) => `₹${n.toLocaleString("en-IN")}`;

export function Pricing() {
  const [yearly, setYearly] = useState(true);

  return (
    <div>
      <div className="flex justify-center">
        <div role="radiogroup" aria-label="Billing period" className="inline-flex rounded-xl border border-line bg-surface p-1">
          {[
            { value: false, label: "Monthly" },
            { value: true, label: "Yearly" },
          ].map((o) => (
            <button
              key={o.label}
              type="button"
              role="radio"
              aria-checked={yearly === o.value}
              onClick={() => setYearly(o.value)}
              className={`rounded-lg px-4 py-1.5 text-sm font-semibold transition-colors ${
                yearly === o.value ? "bg-brand text-brand-fg" : "text-muted hover:text-fg"
              }`}
            >
              {o.label}
              {o.value && <span className="ml-1.5 text-xs font-medium opacity-80">save 25%</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-10 grid items-stretch gap-5 lg:grid-cols-3">
        {PLANS.map((plan) => {
          const amount = plan.monthly === null ? null : yearly ? Math.round(plan.monthly * 0.75) : plan.monthly;
          return (
            <section
              key={plan.name}
              aria-labelledby={`plan-${plan.name}`}
              className={`relative flex flex-col rounded-3xl border p-7 shadow-card ${
                plan.highlight ? "border-brand bg-surface ring-4 ring-[var(--ring)]" : "border-line bg-surface"
              }`}
            >
              {plan.highlight && (
                <span className="absolute -top-3 left-7 rounded-full bg-brand px-3 py-1 text-xs font-semibold text-brand-fg">
                  Most popular
                </span>
              )}
              <h3 id={`plan-${plan.name}`} className="font-display text-xl font-bold text-fg">
                {plan.name}
              </h3>
              <p className="mt-1 text-sm text-muted">{plan.blurb}</p>
              <p className="mt-6 flex items-baseline gap-1.5">
                {amount === null ? (
                  <span className="font-display text-4xl font-bold text-fg">Custom</span>
                ) : (
                  <>
                    <span className="font-display text-4xl font-bold text-fg">{price(amount)}</span>
                    <span className="text-sm text-muted">/ month{amount > 0 && yearly ? ", billed yearly" : ""}</span>
                  </>
                )}
              </p>
              <Link
                href={plan.cta.href}
                className={`mt-6 rounded-xl px-4 py-3 text-center text-sm font-semibold transition-colors ${
                  plan.highlight
                    ? "bg-brand text-brand-fg hover:bg-brand-hover"
                    : "border border-line bg-surface text-fg hover:bg-surface-2"
                }`}
              >
                {plan.cta.label}
              </Link>
              <ul className="mt-7 space-y-3 text-sm">
                {plan.features.map((f) => (
                  <li key={f} className="flex gap-2.5 text-fg">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />
                    {f}
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
