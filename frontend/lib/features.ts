// Core (⭐) features from PLAN.md, shown as a roadmap on each portal.

import type { Role } from "./session";

export type Feature = { id: string; name: string; phase: number };

export const ROADMAP: Record<Role, Feature[]> = {
  student: [
    { id: "S1", name: "Ask a doubt, get a streamed answer", phase: 1 },
    { id: "S2", name: "Citations (file + page) under every answer", phase: 2 },
    { id: "S3", name: "Answers only from your enrolled courses", phase: 2 },
    { id: "S4", name: "Follow-up questions work", phase: 2 },
    { id: "S9", name: "\"I don't understand X\" → learning path", phase: 3 },
    { id: "S12", name: "Assistant remembers your weak topics", phase: 4 },
    { id: "S13", name: "Practice questions from weak topics", phase: 4 },
    { id: "S18", name: "Login/payment issues go to support", phase: 4 },
    { id: "S6", name: "👍 / 👎 feedback, 👎 creates a ticket", phase: 5 },
  ],
  teacher: [
    { id: "T1", name: "Upload HTML, DOC, PDF, TXT", phase: 1 },
    { id: "T2", name: "Processing status per file", phase: 1 },
    { id: "T3", name: "Auto tags (topic, difficulty, type)", phase: 1 },
    { id: "T6", name: "LLM extracts concepts and prerequisites", phase: 3 },
    { id: "T7", name: "Approve / edit / merge concepts", phase: 3 },
    { id: "T10", name: "Generate quizzes from documents", phase: 3 },
    { id: "T13", name: "Most asked doubts (grouped by meaning)", phase: 5 },
    { id: "T14", name: "Content gaps: questions the AI couldn't answer", phase: 5 },
  ],
  support: [
    { id: "P1", name: "Ticket queue", phase: 5 },
    { id: "P2", name: "Auto tickets: low confidence, 👎, non-academic", phase: 5 },
    { id: "P3", name: "Full context: query, chunks, AI draft, confidence", phase: 5 },
    { id: "P4", name: "Edit the AI draft and resolve", phase: 5 },
    { id: "P5", name: "Resolved answer saved back to the knowledge base", phase: 5 },
  ],
  admin: [
    { id: "A1", name: "Ask in plain English → SQL, answer, chart", phase: 6 },
    { id: "A2", name: "SQL agent fixes its own errors", phase: 6 },
    { id: "A3", name: "Read-only DB user, SELECT only", phase: 6 },
    { id: "A4", name: "Token cost dashboard", phase: 7 },
    { id: "A5", name: "Latency dashboard", phase: 7 },
    { id: "A6", name: "Answer quality dashboard", phase: 7 },
  ],
};
