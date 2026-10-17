// Sidebar items and the roadmap of core (⭐) features from PLAN.md.

import {
  BookOpen,
  ChartColumn,
  Dumbbell,
  Gauge,
  Inbox,
  LayoutDashboard,
  ListChecks,
  Plug,
  MessageCircleQuestion,
  Network,
  Route,
  ShieldCheck,
  Ticket,
  Upload,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

import type { Role } from "./session";

// Phase whose features are built. Roadmap items up to this phase show as "Live".
export const CURRENT_PHASE = 7;

// href = page exists; phase = arrives in that phase (greyed out until then)
export type NavItem = { label: string; icon: LucideIcon; href?: string; phase?: number };

export const NAV: Record<Role, NavItem[]> = {
  student: [
    { label: "Dashboard", icon: LayoutDashboard, href: "/student" },
    { label: "Ask a doubt", icon: MessageCircleQuestion, href: "/student/ask" },
    { label: "Learning path", icon: Route, href: "/student/path" },
    { label: "Quizzes", icon: ListChecks, href: "/student/quizzes" },
    { label: "Practice", icon: Dumbbell, href: "/student/ask?q=Quiz%20me%20on%20my%20weak%20topics" },
    { label: "MCP access", icon: Plug, href: "/student/mcp" },
    { label: "My tickets", icon: Ticket, href: "/student/tickets" },
    { label: "Ask the data", icon: ChartColumn, href: "/student/data" },
  ],
  teacher: [
    { label: "Dashboard", icon: LayoutDashboard, href: "/teacher" },
    { label: "Course files", icon: Upload, href: "/teacher/files" },
    { label: "Concept graph", icon: Network, href: "/teacher/concepts" },
    { label: "Quizzes", icon: ListChecks, href: "/teacher/quizzes" },
    { label: "MCP access", icon: Plug, href: "/teacher/mcp" },
    { label: "Doubt insights", icon: BookOpen, href: "/teacher/insights" },
    { label: "Ask the data", icon: ChartColumn, href: "/teacher/data" },
  ],
  support: [
    { label: "Dashboard", icon: LayoutDashboard, href: "/support" },
    { label: "Ticket queue", icon: Inbox, href: "/support/tickets" },
    { label: "Knowledge base", icon: ShieldCheck, href: "/support/kb" },
    { label: "MCP access", icon: Plug, href: "/support/mcp" },
    { label: "Ask the data", icon: ChartColumn, href: "/support/data" },
  ],
  admin: [
    { label: "Dashboard", icon: LayoutDashboard, href: "/admin" },
    { label: "Users & roles", icon: UsersRound, href: "/admin/users" },
    { label: "Tickets", icon: Inbox, href: "/admin/tickets" },
    { label: "MCP access", icon: Plug, href: "/admin/mcp" },
    { label: "Ask the data", icon: ChartColumn, href: "/admin/data" },
    { label: "AI quality & cost", icon: Gauge, href: "/admin/quality" },
  ],
};

// live = built ahead of CURRENT_PHASE (a phase delivered in parts)
export type Feature = { id: string; name: string; phase: number; live?: boolean };

export const ROADMAP: Record<Role, Feature[]> = {
  student: [
    { id: "S1", name: "Ask a doubt, get a streamed answer", phase: 1 },
    { id: "S2", name: "Citations (file + page) under every answer", phase: 2 },
    { id: "S3", name: "Answers only from your enrolled courses", phase: 2 },
    { id: "S4", name: "Follow-up questions work", phase: 2 },
    { id: "S9", name: "\"I don't understand X\" → learning path", phase: 3, live: true },
    { id: "S15", name: "Take teacher-approved quizzes", phase: 3, live: true },
    { id: "S12", name: "Assistant remembers your weak topics", phase: 4 },
    { id: "S13", name: "Practice questions from weak topics", phase: 4 },
    { id: "S18", name: "Login/payment issues go to support", phase: 4 },
    { id: "M3", name: "Use your course notes from Claude Desktop / Cursor (MCP)", phase: 4 },
    { id: "S6", name: "👍 / 👎 feedback, 👎 creates a ticket", phase: 5 },
    { id: "S19", name: "See your tickets and support's answers", phase: 5 },
    { id: "S16", name: "Ask about your own data in plain English", phase: 6 },
    { id: "S8", name: "Off-topic questions politely refused", phase: 7 },
  ],
  teacher: [
    { id: "T1", name: "Upload HTML, DOC, PDF, TXT", phase: 1 },
    { id: "T2", name: "Processing status per file", phase: 1 },
    { id: "T3", name: "Auto tags (topic, difficulty, type)", phase: 1 },
    { id: "T6", name: "LLM extracts concepts and prerequisites", phase: 3, live: true },
    { id: "T7", name: "Approve / edit / merge concepts", phase: 3, live: true },
    { id: "T10", name: "Generate quizzes from documents", phase: 3, live: true },
    { id: "T11", name: "Approve / edit quiz questions (with source passage)", phase: 3, live: true },
    { id: "M7", name: "Query your students from any MCP client", phase: 4 },
    { id: "T13", name: "Most asked doubts (grouped by meaning)", phase: 5 },
    { id: "T14", name: "Content gaps: questions the AI couldn't answer", phase: 5 },
    { id: "T15", name: "Ask about your students in plain English (results, chart, SQL)", phase: 6 },
  ],
  support: [
    { id: "P1", name: "Ticket queue", phase: 5 },
    { id: "P2", name: "Auto tickets: low confidence, 👎, non-academic", phase: 5 },
    { id: "P3", name: "Full context: query, chunks, AI draft, confidence", phase: 5 },
    { id: "P4", name: "Edit the AI draft and resolve", phase: 5 },
    { id: "P5", name: "Resolved answer saved back to the knowledge base", phase: 5 },
    { id: "P7", name: "Similar past tickets", phase: 5 },
    { id: "P8", name: "Ask about a ticket's student in plain English (only while it is open)", phase: 6 },
  ],
  admin: [
    { id: "A1", name: "Ask in plain English → SQL, answer, chart", phase: 6 },
    { id: "A2", name: "SQL agent fixes its own errors", phase: 6 },
    { id: "A3", name: "Read-only DB user, SELECT only", phase: 6 },
    { id: "M11", name: "MCP access tokens, audit log and rate limits", phase: 4 },
    { id: "A4", name: "Token cost dashboard", phase: 7 },
    { id: "A5", name: "Latency dashboard", phase: 7 },
    { id: "A6", name: "Answer quality dashboard", phase: 7 },
    { id: "A8", name: "Run the eval set and compare versions", phase: 7 },
    { id: "A9", name: "Guardrail log", phase: 7 },
  ],
};
