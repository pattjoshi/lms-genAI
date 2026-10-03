// Every backend call goes through apiFetch: it adds the dummy-login header and
// turns the backend's {"error", "message"} responses into a readable ApiError.

import { getUser } from "./session";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public detail?: string,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const user = getUser();
  const headers = new Headers(init.headers);
  // FormData (file upload) must set its own multipart boundary header.
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (user) headers.set("X-User-Id", String(user.id));

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "backend_unreachable", `Cannot reach the backend at ${API_URL}. Is it running?`);
  }

  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(
      res.status,
      body?.error ?? `http_${res.status}`,
      body?.message ?? res.statusText,
      body?.detail,
    );
  }
  return body as T;
}
