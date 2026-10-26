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
  return useQuery({ queryKey: ["auth-config"], queryFn: () => api.get<{ google_client_id: string | null; google_domains: string[]; notice?: string; email_notifications?: boolean; ms_client_id?: string | null; ms_tenant_id?: string | null }>("/auth/config"), staleTime: Infinity });
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


// ------------------------------------------------------------------ Sign in with Microsoft (work accounts)
// Opens Microsoft's sign-in in a small window; the ID token comes back to /auth/microsoft on this site and is passed to
// the server, which checks Microsoft's signature, this app's ID and the one-time nonce. No extra library needed.
const MS_STATE = "rf.ms.pending";
const MS_RESULT = "rf.ms.result";

function rand() {
  const a = new Uint8Array(24);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

function MicrosoftLogo() {
  return (
    <svg viewBox="0 0 21 21" className="h-[18px] w-[18px]" aria-hidden>
      <rect x="1" y="1" width="9" height="9" fill="#F25022" /><rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" /><rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}

export function MicrosoftButton({ onCredential, label = "Sign in with Microsoft" }: { onCredential: (idToken: string, nonce: string) => void; label?: string }) {
  const { data: cfg } = useAuthConfig();
  const [busy, setBusy] = useState(false);
  const cb = useRef(onCredential);
  cb.current = onCredential;

  // Back from a full-page sign-in (when the popup was blocked)
  useEffect(() => {
    try {
      const done = JSON.parse(sessionStorage.getItem(MS_RESULT) || "null");
      const pending = JSON.parse(sessionStorage.getItem(MS_STATE) || "null");
      if (done && pending && done.state === pending.state && done.id_token) {
        sessionStorage.removeItem(MS_RESULT);
        sessionStorage.removeItem(MS_STATE);
        cb.current(done.id_token, pending.nonce);
      }
    } catch { /* ignore */ }
  }, []);

  if (!cfg?.ms_client_id) return null;
  const start = () => {
    const state = rand(), nonce = rand();
    try { sessionStorage.setItem(MS_STATE, JSON.stringify({ state, nonce, back: window.location.pathname })); } catch { /* ignore */ }
    const q = new URLSearchParams({
      client_id: cfg.ms_client_id!, response_type: "id_token", redirect_uri: `${window.location.origin}/auth/microsoft`,
      scope: "openid profile email", response_mode: "fragment", state, nonce, prompt: "select_account",
    });
    const url = `https://login.microsoftonline.com/${cfg.ms_tenant_id || "organizations"}/oauth2/v2.0/authorize?${q}`;
    const w = 480, h = 640;
    const popup = window.open(url, "rf-ms-signin", `width=${w},height=${h},left=${window.screenX + (window.outerWidth - w) / 2},top=${window.screenY + (window.outerHeight - h) / 2}`);
    if (!popup) return window.location.assign(url);  // popup blocked: sign in on this page instead
    setBusy(true);
    const onMsg = (e: MessageEvent) => {
      if (e.origin !== window.location.origin || e.data?.type !== "rf-ms-signin") return;
      window.removeEventListener("message", onMsg);
      clearInterval(timer);
      setBusy(false);
      if (e.data.state === state && e.data.id_token) cb.current(e.data.id_token, nonce);
    };
    window.addEventListener("message", onMsg);
    const timer = window.setInterval(() => { if (popup.closed) { clearInterval(timer); window.removeEventListener("message", onMsg); setBusy(false); } }, 600);
  };
  return (
    <button type="button" onClick={start} disabled={busy}
      className="mb-3 flex h-10 w-full items-center justify-center gap-2.5 rounded-[10px] border border-[#8C8C8C]/40 bg-white text-[14px] font-semibold text-[#3C4043] transition-colors hover:bg-[#F7F8F8] disabled:opacity-60">
      <MicrosoftLogo /> {busy ? "Waiting for Microsoft…" : label}
    </button>
  );
}

/** Page Microsoft returns to (/auth/microsoft): hands the token to the window that opened it, then closes. */
export function MicrosoftCallback() {
  useEffect(() => {
    const p = new URLSearchParams(window.location.hash.slice(1));
    const msg = { type: "rf-ms-signin", id_token: p.get("id_token"), state: p.get("state"), error: p.get("error_description") || p.get("error") };
    try {
      if (window.opener && window.opener.location.origin === window.location.origin) {
        window.opener.postMessage(msg, window.location.origin);
        window.close();
        return;
      }
    } catch { /* opener on another site: fall through to this-page sign-in */ }
    try {
      sessionStorage.setItem(MS_RESULT, JSON.stringify(msg));
      const back = JSON.parse(sessionStorage.getItem(MS_STATE) || "{}").back || "/login";
      window.location.replace(back);
    } catch {
      window.location.replace("/login");
    }
  }, []);
  return <div className="min-h-screen grid place-items-center text-ink-muted text-sm">Signing you in…</div>;
}
