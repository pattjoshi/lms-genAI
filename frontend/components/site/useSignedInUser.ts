"use client";

import { useEffect, useState } from "react";

import { getUser, type SessionUser } from "@/lib/session";

/** The cached logged-in user, read after mount (so server and first client render match). */
export function useSignedInUser() {
  const [user, setUser] = useState<SessionUser | null>(null);
  useEffect(() => setUser(getUser()), []);
  return user;
}
