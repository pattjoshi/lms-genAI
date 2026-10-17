"use client";

import { useApi } from "@/components/useApi";

export type AuthConfig = {
  google_client_id: string | null;
  signup_open: boolean;
  demo_login: boolean;
  password_min_length: number;
};

export function useAuthConfig() {
  return useApi<AuthConfig>("/auth/config");
}
