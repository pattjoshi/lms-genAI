import Link from "next/link";

import { Logo } from "./Logo";

const COLUMNS = [
  {
    title: "Learn",
    links: [
      { href: "/courses", label: "All courses" },
      { href: "/courses?category=AI%20and%20machine%20learning", label: "AI and machine learning" },
      { href: "/courses?category=Programming", label: "Programming" },
      { href: "/courses?category=Data", label: "Data" },
    ],
  },
  {
    title: "Product",
    links: [
      { href: "/#how-it-works", label: "How it works" },
      { href: "/#features", label: "AI tutor" },
      { href: "/#teams", label: "For teams" },
      { href: "/#pricing", label: "Pricing" },
    ],
  },
  {
    title: "Account",
    links: [
      { href: "/login", label: "Log in" },
      { href: "/signup", label: "Create an account" },
      { href: "/#faq", label: "Help and FAQ" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div className="max-w-sm">
          <Logo />
          <p className="mt-4 text-sm leading-relaxed text-muted">
            Courses with an AI tutor built in. Every answer comes from your course material and shows where it came
            from.
          </p>
        </div>
        {COLUMNS.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <h2 className="text-sm font-semibold text-fg">{col.title}</h2>
            <ul className="mt-3 space-y-2.5">
              {col.links.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className="text-sm text-muted transition-colors hover:text-fg">
                    {l.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-5 text-xs text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>© {new Date().getFullYear()} LMS GenAI. A GenAI learning project.</p>
          <p>Built with RAG, a concept graph, guardrails and evaluation.</p>
        </div>
      </div>
    </footer>
  );
}
