import { GraduationCap } from "lucide-react";
import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2.5 rounded-xl" aria-label="LMS GenAI home">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand text-brand-fg shadow-card">
        <GraduationCap className="h-5 w-5" aria-hidden />
      </span>
      <span className="font-display text-[17px] font-bold tracking-tight text-fg">LMS GenAI</span>
    </Link>
  );
}
