import type { Metadata } from "next";

export const metadata: Metadata = { title: "Courses · LMS GenAI" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
