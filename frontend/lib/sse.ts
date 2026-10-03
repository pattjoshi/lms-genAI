// Read a Server-Sent Events stream from a POST request.
// (The browser's EventSource only supports GET and can't send our X-User-Id header,
// so we read the response body stream ourselves.)

import { API_URL, ApiError } from "./api";
import { getUser } from "./session";

export async function streamSSE(
  path: string,
  body: unknown,
  onEvent: (event: string, data: any) => void,
  signal?: AbortSignal,
): Promise<void> {
  const user = getUser();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(user ? { "X-User-Id": String(user.id) } : {}) },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    throw new ApiError(0, "backend_unreachable", `Cannot reach the backend at ${API_URL}. Is it running?`);
  }
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => null);
    throw new ApiError(res.status, err?.error ?? `http_${res.status}`, err?.message ?? res.statusText, err?.detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Events are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (dataLines.length) onEvent(event, JSON.parse(dataLines.join("\n")));
    }
  }
}
