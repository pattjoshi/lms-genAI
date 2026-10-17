"use client";

// "Continue with Google" using Google Identity Services. Google gives the browser a signed ID token;
// the backend checks it (POST /auth/google) and starts a normal session. No Google password ever
// reaches us. Shown only when the backend has a GOOGLE_CLIENT_ID.

import Script from "next/script";
import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type { SessionUser } from "@/lib/session";

type GoogleId = {
  initialize: (o: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string }) => void;
  renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
};
declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } };
  }
}

export function GoogleButton({
  clientId,
  text = "continue_with",
  onSignedIn,
  onError,
}: {
  clientId: string;
  text?: "continue_with" | "signup_with" | "signin_with";
  onSignedIn: (user: SessionUser & { created?: boolean }) => void;
  onError: (message: string) => void;
}) {
  const slot = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [width, setWidth] = useState(360);

  const onCredential = useCallback(
    async ({ credential }: { credential: string }) => {
      try {
        onSignedIn(await apiFetch("/auth/google", { method: "POST", body: JSON.stringify({ credential }) }));
      } catch (e) {
        onError(e instanceof ApiError ? e.message : String(e));
      }
    },
    [onSignedIn, onError],
  );

  useEffect(() => {
    if (!slot.current) return;
    const resize = () => setWidth(Math.min(400, slot.current?.offsetWidth ?? 360));
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  useEffect(() => {
    const id = window.google?.accounts.id;
    if (!ready || !id || !slot.current) return;
    id.initialize({ client_id: clientId, callback: onCredential });
    const dark = document.documentElement.classList.contains("dark");
    id.renderButton(slot.current, {
      type: "standard",
      theme: dark ? "filled_black" : "outline",
      size: "large",
      shape: "pill",
      text,
      width,
      logo_alignment: "center",
    });
  }, [ready, clientId, onCredential, text, width]);

  return (
    <>
      <Script src="https://accounts.google.com/gsi/client" strategy="afterInteractive" onReady={() => setReady(true)} />
      <div ref={slot} className="flex min-h-[44px] w-full justify-center" />
    </>
  );
}
