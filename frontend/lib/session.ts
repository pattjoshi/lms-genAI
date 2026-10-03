// Dummy login: the chosen user is kept in localStorage. No password, no token.

export type Role = "student" | "teacher" | "admin" | "support";

export type SessionUser = {
  id: number;
  full_name: string;
  email: string;
  role: Role;
  city: string;
  story: string | null;
};

const KEY = "lms_user";

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
  window.localStorage.setItem(KEY, JSON.stringify(user));
}

export function clearUser() {
  window.localStorage.removeItem(KEY);
}
