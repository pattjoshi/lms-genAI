// Every backend call goes through apiFetch: it sends the session cookie and turns the
// backend's {"error", "message"} responses into a readable ApiError.

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

// Fired when the backend says the session ended (expired, logged out elsewhere, deactivated).
// PortalShell listens and sends the user to the login page.
export const UNAUTHORIZED_EVENT = "lms:unauthorized";

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  // FormData (file upload) must set its own multipart boundary header.
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    // credentials: "include" sends the httpOnly session cookie to the backend (another port = another origin).
    res = await fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
  } catch {
    throw new ApiError(0, "backend_unreachable", `Cannot reach the backend at ${API_URL}. Is it running?`);
  }

  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(
      res.status,
      body?.error ?? `http_${res.status}`,
      body?.message ?? res.statusText,
      body?.detail,
    );
  }
  return body as T;
}
