import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LMS GenAI",
  description: "AI learning assistant for an LMS — a GenAI learning project",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full bg-slate-100 text-slate-900">{children}</body>
    </html>
  );
}
