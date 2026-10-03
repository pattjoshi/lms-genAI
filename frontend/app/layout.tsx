import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";

import { THEME_INIT_SCRIPT } from "@/lib/theme";
import "./globals.css";

// next/font downloads these at build/dev time and serves them from our own app:
// no request to Google from the user's browser.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-jakarta" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains" });

export const metadata: Metadata = {
  title: "LMS GenAI",
  description: "AI learning assistant for an LMS — a GenAI learning project",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning: the theme script adds the "dark" class before React loads.
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${jakarta.variable} ${jetbrains.variable} h-full antialiased`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full bg-bg text-fg">{children}</body>
    </html>
  );
}
