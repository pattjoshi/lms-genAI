"use client";

import { useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";

/** Load a GET endpoint once. Returns { data, error }. */
export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<T>(path)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e))));
    return () => {
      cancelled = true;
    };
  }, [path]);

  return { data, error };
}
