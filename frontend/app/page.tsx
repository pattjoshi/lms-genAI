// Public landing page. Server component: the copy is in the HTML for search engines and fast first
// paint; the live parts (stats, catalogue, pricing toggle) are small client components.

import {
  ArrowRight,
  BadgeCheck,
  ChartColumn,
  FileText,
  LifeBuoy,
  ListChecks,
  Plug,
  Quote,
  Route,
  ShieldCheck,
  Sparkles,
  Star,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { AssistantPreview } from "@/components/site/AssistantPreview";
import { AudienceTabs } from "@/components/site/AudienceTabs";
import { HeroSearch } from "@/components/site/HeroSearch";
import { CategoryGrid, FeaturedCourses, LiveStats } from "@/components/site/LandingCatalog";
import { Pricing } from "@/components/site/Pricing";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";

export const metadata: Metadata = {
  title: "LMS GenAI: courses with an AI tutor that cites your material",
  description:
    "Learn programming, AI and data with an AI tutor that answers from your course, shows its sources, and builds practice around your weak topics.",
};

const FEATURES: { icon: typeof Sparkles; title: string; text: string; wide?: boolean }[] = [
  {
    icon: FileText,
    title: "Answers you can check",
    text: "Every answer comes from your course files and links the page it used. If the material doesn't cover it, the tutor says so instead of guessing.",
    wide: true,
  },
  {
    icon: Route,
    title: "Learning paths",
    text: "Say what confuses you. Get the prerequisites in order, with the ones you already know ticked off.",
  },
  {
    icon: ListChecks,
    title: "Quizzes checked against the source",
    text: "Generated from the lesson, approved by your instructor, explained after you answer.",
  },
  {
    icon: LifeBuoy,
    title: "A human when it matters",
    text: "Unsure answers, a 👎 or a payment problem go straight to the support team, with the full context.",
  },
  {
    icon: Plug,
    title: "Works where you work",
    text: "Use your courses from Claude Desktop or Cursor through MCP, with the same permissions.",
  },
  {
    icon: ShieldCheck,
    title: "Safe by design",
    text: "Off-topic and manipulative prompts are refused. Roles decide what each person can see, on every request.",
    wide: true,
  },
  {
    icon: ChartColumn,
    title: "Ask your data",
    text: "\"Which topics do my students fail most?\" Get a chart and the SQL, limited to what you may see.",
  },
];

// Sample quotes for the template. Replace them with real, permissioned learner quotes before launch.
const TESTIMONIALS = [
  {
    quote:
      "I used to lose a whole evening on one confusing slide. Now I ask, read the page it points to, and move on.",
    name: "Priya",
    role: "Final-year CS student",
  },
  {
    quote:
      "The doubt insights showed me three topics half my class was stuck on. I re-recorded those lectures the same week.",
    name: "Vikram",
    role: "Python instructor",
  },
  {
    quote: "The learning path skipped what I already knew. I went from 'what is a gradient' to backprop in two days.",
    name: "Arjun",
    role: "Working professional",
  },
];

const FAQ = [
  {
    q: "Where do the AI tutor's answers come from?",
    a: "From the files of the courses you're enrolled in. Each answer cites the file and page. If nothing relevant is found, the tutor says it doesn't know and can pass your question to the support team.",
  },
  {
    q: "Can I sign in with Google?",
    a: "Yes. Use \"Continue with Google\" on the log-in or sign-up page. If you already have an account with the same email, the two are linked.",
  },
  {
    q: "I'm an instructor. How do I get access?",
    a: "Create an account, then ask your organisation's admin to give you the instructor role. Admins manage roles on the Users page.",
  },
  {
    q: "Is my data private?",
    a: "Students only ever see their own records. Instructors see their own courses' students, and support only sees a student while a ticket is open. These rules are enforced by the server and the database, not by the AI.",
  },
  {
    q: "Can I cancel any time?",
    a: "Yes. Plans renew monthly or yearly and you can cancel before the next renewal.",
  },
];

function SectionHeading({ eyebrow, title, text, id }: { eyebrow: string; title: ReactNode; text?: string; id: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="text-sm font-semibold uppercase tracking-wider text-brand-ink">{eyebrow}</p>
      <h2 id={id} className="mt-2 font-display text-3xl font-bold tracking-tight text-fg sm:text-4xl">
        {title}
      </h2>
      {text && <p className="mt-3 text-base text-muted sm:text-lg">{text}</p>}
    </div>
  );
}

export default function LandingPage() {
  return (
    <>
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-brand px-4 py-2 text-brand-fg focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>
      <SiteHeader />

      <main id="main">
        {/* Hero */}
        <section aria-labelledby="hero-title" className="relative overflow-hidden">
          <div className="pointer-events-none absolute inset-0 -z-10">
            <div className="absolute -top-40 left-1/2 h-[36rem] w-[60rem] -translate-x-1/2 rounded-full bg-brand/15 blur-3xl" />
            <div className="absolute inset-0 bg-[linear-gradient(to_right,var(--line)_1px,transparent_1px),linear-gradient(to_bottom,var(--line)_1px,transparent_1px)] bg-[size:56px_56px] opacity-40 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_70%)]" />
          </div>
          <div className="mx-auto grid max-w-7xl items-center gap-14 px-4 pb-20 pt-10 sm:px-6 sm:pt-16 lg:grid-cols-[1.05fr_1fr] lg:gap-10 lg:pb-28">
            <div>
              <p className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/80 px-3 py-1 text-xs font-semibold text-brand-ink shadow-card">
                <Sparkles className="h-3.5 w-3.5" aria-hidden /> An AI tutor inside every course
              </p>
              <h1
                id="hero-title"
                className="mt-5 font-display text-4xl font-extrabold leading-[1.08] tracking-tight text-fg sm:text-5xl lg:text-6xl"
              >
                Learn faster with a tutor that{" "}
                <span className="bg-gradient-to-r from-brand to-[#22b8cf] bg-clip-text text-transparent">
                  knows your course
                </span>
                .
              </h1>
              <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">
                Ask any doubt and get an answer from your own course material, with the page it came from. Then practise
                exactly what you&apos;re weak at.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link
                  href="/signup"
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand px-6 py-3.5 text-base font-semibold text-brand-fg shadow-card transition-colors hover:bg-brand-hover"
                >
                  Start learning free <ArrowRight className="h-4 w-4" aria-hidden />
                </Link>
                <Link
                  href="/courses"
                  className="inline-flex items-center justify-center rounded-xl border border-line bg-surface px-6 py-3.5 text-base font-semibold text-fg transition-colors hover:bg-surface-2"
                >
                  Browse courses
                </Link>
              </div>
              <div className="mt-8 max-w-xl">
                <HeroSearch />
              </div>
              <div className="mt-10">
                <LiveStats />
              </div>
            </div>
            <AssistantPreview />
          </div>
        </section>

        {/* Categories */}
        <section aria-labelledby="explore" className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
          <SectionHeading
            id="explore"
            eyebrow="Explore"
            title="Find your next skill"
            text="Hands-on courses taught by working instructors, from your first line of Python to transformers."
          />
          <div className="mt-10">
            <CategoryGrid />
          </div>
        </section>

        {/* Featured courses */}
        <section aria-labelledby="popular" className="bg-surface-2/50 py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
              <div>
                <p className="text-sm font-semibold uppercase tracking-wider text-brand-ink">Popular now</p>
                <h2 id="popular" className="mt-2 font-display text-3xl font-bold tracking-tight text-fg sm:text-4xl">
                  Courses learners love
                </h2>
              </div>
              <Link href="/courses" className="hidden text-sm font-semibold text-brand-ink hover:underline sm:block">
                View the full catalogue →
              </Link>
            </div>
            <div className="mt-10">
              <FeaturedCourses />
            </div>
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" aria-labelledby="how" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-20 sm:px-6">
          <SectionHeading id="how" eyebrow="How it works" title="Three steps, no guesswork" />
          <ol className="mt-12 grid gap-6 md:grid-cols-3">
            {[
              ["Pick a course", "Enroll in a course and work through lessons at your pace, on any device."],
              ["Ask while you learn", "Stuck? Ask in your own words. The answer cites the exact page of your material."],
              ["Practise the gaps", "The tutor remembers weak topics and builds a path and quizzes around them."],
            ].map(([title, text], i) => (
              <li key={title} className="relative rounded-3xl border border-line bg-surface p-7 shadow-card">
                <span className="font-display text-5xl font-extrabold text-brand/25">0{i + 1}</span>
                <h3 className="mt-3 font-display text-xl font-semibold text-fg">{title}</h3>
                <p className="mt-2 text-muted">{text}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* Features bento */}
        <section id="features" aria-labelledby="features-title" className="scroll-mt-20 bg-surface-2/50 py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6">
            <SectionHeading
              id="features-title"
              eyebrow="The AI tutor"
              title="More than a chatbot on top of videos"
              text="Built for learning: grounded in your material, honest about what it doesn't know, and backed by people."
            />
            <ul className="mt-12 grid gap-5 md:grid-cols-3">
              {FEATURES.map(({ icon: Icon, title, text, wide }) => (
                <li
                  key={title}
                  className={`rounded-3xl border border-line bg-surface p-6 shadow-card ${wide ? "md:col-span-2" : ""}`}
                >
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-ink">
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                  <h3 className="mt-4 font-display text-lg font-semibold text-fg">{title}</h3>
                  <p className="mt-1.5 text-muted">{text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Who it's for */}
        <section id="teams" aria-labelledby="who" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-20 sm:px-6">
          <SectionHeading id="who" eyebrow="Who it's for" title="Built for everyone in the classroom" />
          <div className="mt-10">
            <AudienceTabs />
          </div>
        </section>

        {/* Social proof */}
        <section aria-labelledby="voices" className="bg-surface-2/50 py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6">
            <SectionHeading id="voices" eyebrow="Learners and instructors" title="What changes when doubts get answered" />
            <ul className="mt-12 grid gap-5 md:grid-cols-3">
              {TESTIMONIALS.map((t) => (
                <li key={t.name}>
                  <figure className="flex h-full flex-col rounded-3xl border border-line bg-surface p-7 shadow-card">
                    <div className="flex gap-0.5 text-warn" aria-label="5 out of 5">
                      {Array.from({ length: 5 }, (_, i) => (
                        <Star key={i} className="h-4 w-4 fill-current" aria-hidden />
                      ))}
                    </div>
                    <Quote className="mt-4 h-6 w-6 text-brand/40" aria-hidden />
                    <blockquote className="mt-2 flex-1 text-fg">{t.quote}</blockquote>
                    <figcaption className="mt-6 flex items-center gap-3">
                      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-soft font-display font-semibold text-brand-ink">
                        {t.name[0]}
                      </span>
                      <span>
                        <span className="block text-sm font-semibold text-fg">{t.name}</span>
                        <span className="block text-xs text-muted">{t.role}</span>
                      </span>
                    </figcaption>
                  </figure>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Pricing */}
        <section id="pricing" aria-labelledby="pricing-title" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-20 sm:px-6">
          <SectionHeading
            id="pricing-title"
            eyebrow="Pricing"
            title="Start free. Upgrade when it clicks."
            text="Simple plans in rupees. Cancel any time."
          />
          <div className="mt-10">
            <Pricing />
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" aria-labelledby="faq-title" className="scroll-mt-20 bg-surface-2/50 py-20">
          <div className="mx-auto max-w-3xl px-4 sm:px-6">
            <SectionHeading id="faq-title" eyebrow="FAQ" title="Questions, answered" />
            <div className="mt-10 divide-y divide-line rounded-3xl border border-line bg-surface shadow-card">
              {FAQ.map((f) => (
                <details key={f.q} className="group p-5 sm:p-6">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-display font-semibold text-fg [&::-webkit-details-marker]:hidden">
                    {f.q}
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line text-muted transition-transform group-open:rotate-45">
                      +
                    </span>
                  </summary>
                  <p className="mt-3 text-muted">{f.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* Final call to action */}
        <section aria-labelledby="cta" className="px-4 py-20 sm:px-6">
          <div className="relative mx-auto max-w-6xl overflow-hidden rounded-[2rem] bg-gradient-to-br from-[#4f46e5] via-[#6d5efc] to-[#0891b2] px-6 py-16 text-center text-white shadow-card sm:px-12">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_10%,rgba(255,255,255,0.25),transparent_40%)]" />
            <BadgeCheck className="relative mx-auto h-10 w-10 opacity-90" aria-hidden />
            <h2 id="cta" className="relative mt-4 font-display text-3xl font-bold tracking-tight sm:text-4xl">
              Your next “aha” is one question away
            </h2>
            <p className="relative mx-auto mt-3 max-w-xl text-white/85">
              Create a free account in under a minute. No card needed.
            </p>
            <div className="relative mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              <Link
                href="/signup"
                className="rounded-xl bg-white px-6 py-3.5 font-semibold text-[#3f37c9] transition-opacity hover:opacity-90"
              >
                Join for free
              </Link>
              <Link
                href="/login"
                className="rounded-xl border border-white/40 px-6 py-3.5 font-semibold text-white transition-colors hover:bg-white/10"
              >
                I already have an account
              </Link>
            </div>
          </div>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
