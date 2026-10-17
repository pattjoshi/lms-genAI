// Who is logged in. The real session is an httpOnly cookie the backend sets (page JavaScript can't
// read it); this file only keeps a copy of the user for the UI and asks the backend when unsure.

import { apiFetch, ApiError } from "./api";

export type Role = "student" | "teacher" | "admin" | "support";

export type SessionUser = {
  id: number;
  full_name: string;
  email: string;
  role: Role;
  city: string;
  story: string | null;
  has_password?: boolean;
  google_linked?: boolean;
};

const KEY = "lms_user";

export const ROLE_LABEL: Record<Role, string> = {
  student: "Student",
  teacher: "Teacher",
  admin: "Admin",
  support: "Support",
};

/** The cached user (may be stale: the backend decides). */
export function getUser(): SessionUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SessionUser) : null;
  } catch {
    return null;
  }
}

export function setUser(user: SessionUser) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(user));
  } catch {
    // storage blocked: the cookie still keeps them logged in
  }
}

export function clearUser() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // nothing cached
  }
}

/** Ask the backend who is logged in. null = nobody (or the session ended). */
export async function fetchMe(): Promise<SessionUser | null> {
  try {
    const me = await apiFetch<SessionUser>("/auth/me");
    setUser(me);
    return me;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      clearUser();
      return null;
    }
    throw e;
  }
}

export async function logout() {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } finally {
    clearUser();
  }
}

/** Where a user lands after logging in: their portal, or the page they were sent away from. */
export function homeFor(user: SessionUser, next?: string | null): string {
  // Only paths on this site (not "//evil.com"), and only inside the user's own portal.
  if (next && next.startsWith(`/${user.role}`) && !next.startsWith("//")) return next;
  return `/${user.role}`;
}
