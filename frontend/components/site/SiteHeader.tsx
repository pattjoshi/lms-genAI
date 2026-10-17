"use client";

import { ArrowRight, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Logo } from "./Logo";
import { useSignedInUser } from "./useSignedInUser";

const LINKS = [
  { href: "/courses", label: "Courses" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#teams", label: "For teams" },
  { href: "/#pricing", label: "Pricing" },
];

export function SiteHeader() {
  const user = useSignedInUser();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`sticky top-0 z-40 border-b transition-colors ${
        scrolled || open ? "border-line bg-bg/85 backdrop-blur-md" : "border-transparent bg-transparent"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-8">
          <Logo />
          <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
            {LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                aria-current={pathname === l.href ? "page" : undefined}
                className="rounded-lg px-3 py-2 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg aria-[current=page]:text-fg"
              >
                {l.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-2">
          <div className="hidden sm:block">
            <ThemeToggle />
          </div>
          {user ? (
            <Link
              href={`/${user.role}`}
              className="hidden items-center gap-1.5 rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-brand-fg transition-colors hover:bg-brand-hover md:inline-flex"
            >
              My dashboard <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          ) : (
            <div className="hidden items-center gap-2 md:flex">
              <Link href="/login" className="rounded-xl px-3 py-2 text-sm font-semibold text-fg hover:bg-surface-2">
                Log in
              </Link>
              <Link
                href="/signup"
                className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-brand-fg shadow-card transition-colors hover:bg-brand-hover"
              >
                Join for free
              </Link>
            </div>
          )}
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? "Close menu" : "Open menu"}
            className="rounded-xl p-2 text-fg hover:bg-surface-2 md:hidden"
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {open && (
        <div id="mobile-menu" className="border-t border-line bg-bg px-4 pb-5 pt-3 md:hidden">
          <nav aria-label="Main mobile" className="grid gap-1">
            {LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className="rounded-xl px-3 py-2.5 text-base font-medium text-fg hover:bg-surface-2"
              >
                {l.label}
              </Link>
            ))}
          </nav>
          <div className="mt-4 grid gap-2">
            {user ? (
              <Link
                href={`/${user.role}`}
                className="rounded-xl bg-brand px-4 py-3 text-center font-semibold text-brand-fg"
              >
                My dashboard
              </Link>
            ) : (
              <>
                <Link href="/signup" className="rounded-xl bg-brand px-4 py-3 text-center font-semibold text-brand-fg">
                  Join for free
                </Link>
                <Link
                  href="/login"
                  className="rounded-xl border border-line px-4 py-3 text-center font-semibold text-fg"
                >
                  Log in
                </Link>
              </>
            )}
            <div className="mt-2 flex items-center justify-between">
              <span className="text-sm text-muted">Theme</span>
              <ThemeToggle />
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
