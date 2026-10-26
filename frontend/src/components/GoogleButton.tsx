import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

declare global {
  interface Window { google?: any }
}

let gisPromise: Promise<void> | null = null;
function loadGis(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  gisPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => { gisPromise = null; reject(new Error("Couldn't load Google sign-in. Check your internet connection.")); };
    document.head.appendChild(s);
  });
  return gisPromise;
}

export function useAuthConfig() {
  return useQuery({ queryKey: ["auth-config"], queryFn: () => api.get<{ google_client_id: string | null; google_domains: string[]; notice?: string }>("/auth/config"), staleTime: Infinity });
}

/** Google's own "Sign in with Google" button. Renders nothing until GOOGLE_CLIENT_ID is set on the server. */
export function GoogleButton({ onCredential, text = "continue_with" }: { onCredential: (credential: string) => void; text?: "signin_with" | "signup_with" | "continue_with" }) {
  const { data } = useAuthConfig();
  const box = useRef<HTMLDivElement>(null);
  const cb = useRef(onCredential);
  cb.current = onCredential;
  const [err, setErr] = useState("");
  useEffect(() => {
    const clientId = data?.google_client_id;
    if (!clientId || !box.current) return;
    let alive = true;
    loadGis()
      .then(() => {
        if (!alive || !box.current) return;
        window.google.accounts.id.initialize({ client_id: clientId, callback: (r: any) => cb.current(r.credential), ux_mode: "popup", auto_select: false });
        box.current.innerHTML = "";
        window.google.accounts.id.renderButton(box.current, { theme: "outline", size: "large", text, shape: "rectangular", logo_alignment: "center", width: Math.min(400, box.current.offsetWidth || 400) });
      })
      .catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [data?.google_client_id, text]);
  if (!data?.google_client_id) return null;
  return (
    <div>
      <div ref={box} className="min-h-[44px] flex justify-center" />
      {err && <div className="text-[12.5px] text-fit-gap-ink mt-2">{err}</div>}
      {data.google_domains?.length > 0 && <div className="text-[12px] text-ink-muted mt-2 text-center">Use your {data.google_domains.map((d) => "@" + d).join(" or ")} account.</div>}
    </div>
  );
}

/** Site-wide notice (e.g. "sample data only" while the AI runs on a free key). Set on the server with PUBLIC_NOTICE. */
export function NoticeBar({ className = "", text }: { className?: string; text?: string }) {
  const { data } = useAuthConfig();
  const notice = text !== undefined ? text : data?.notice;
  if (!notice) return null;
  return (
    <div role="note" className={`bg-[#FBF1DD] text-[#6E4A06] border-b border-[#EED9A8] text-[13px] leading-snug px-4 py-2 text-center ${className}`}>
      {notice}
    </div>
  );
}

export function OrDivider({ label }: { label: string }) {
  const { data } = useAuthConfig();
  if (!data?.google_client_id) return null;
  return (
    <div className="flex items-center gap-3 my-6 text-[12px] text-ink-muted">
      <span className="h-px flex-1 bg-line" />{label}<span className="h-px flex-1 bg-line" />
    </div>
  );
}
