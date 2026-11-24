import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, ShieldCheck, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { PageLoader, ProductMark, Spinner } from "../components/ui";
import { api } from "../lib/api";

/* An AI assistant (Claude, Glean, ...) asks to use this workspace. The person sees who is asking, which company and
   account it will act as, and what it can do, then allows or declines. The assistant gets a token that acts as this
   person only: same role, same masked client names, nothing more. */

const CAN = [
  "Read your deals: verdicts, readiness, requirement gaps, team and price estimates",
  "Search your knowledge library: people by employee code, capabilities, certifications, case studies, accelerators",
  "See the pipeline summary and opportunity radar",
];

export default function Connect() {
  const [sp] = useSearchParams();
  const request = sp.get("request") || "";
  const info = useQuery({
    queryKey: ["mcp-consent", request],
    queryFn: () => api.get(`/mcp/consent?request=${encodeURIComponent(request)}`),
    enabled: !!request,
    retry: false,
  });
  const decide = useMutation({
    mutationFn: (allow: boolean) => api.post<{ redirect: string }>("/mcp/consent", { request, allow }),
    onSuccess: (r) => { window.location.href = r.redirect; },
  });
  const d: any = info.data;
  const canCreate = d && ["admin", "presales"].includes(d.role);

  return (
    <div className="min-h-screen bg-paper grid place-items-center px-4 py-10">
      <div className="w-full max-w-[480px]">
        <div className="mb-6 flex justify-center"><ProductMark /></div>
        <div className="card p-6 md:p-7">
          {!request ? (
            <p className="text-ink-soft text-[14px]">This page is opened by an AI assistant when you connect RevenueForge to it. Start from your assistant's connector settings.</p>
          ) : info.isLoading ? (
            <PageLoader label="Checking the request" />
          ) : info.isError ? (
            <div className="flex gap-3 text-[14px]"><AlertTriangle className="h-5 w-5 text-ember-600 shrink-0" /><span>{(info.error as Error).message}</span></div>
          ) : decide.isSuccess ? (
            <div className="flex items-center gap-2 text-[14px]"><Spinner /> Returning you to {d.client_name}…</div>
          ) : (
            <>
              <div className="text-[12.5px] text-ink-muted">Connection request</div>
              <h1 className="font-display font-semibold text-[24px] leading-[1.1] tracking-[-0.02em] text-brand-950 mt-1">
                Allow {d.client_name} to use {d.company}?
              </h1>
              <p className="text-[13.5px] text-ink-soft mt-2">
                It will act as <span className="font-semibold text-ink">{d.user}</span> ({d.role}), with exactly what that role can do in the app.
                Confidential client names stay masked.
              </p>
              <ul className="mt-4 space-y-2">
                {[...CAN, canCreate ? "Create new deals from an RFP you give it" : null].filter(Boolean).map((t) => (
                  <li key={t} className="flex gap-2 text-[13.5px]"><Check className="h-4 w-4 text-ok mt-0.5 shrink-0" />{t}</li>
                ))}
                <li className="flex gap-2 text-[13.5px] text-ink-muted"><X className="h-4 w-4 mt-0.5 shrink-0" />It can't approve stages, change settings, delete anything or see other companies</li>
              </ul>
              <div className={`mt-5 rounded-lg border p-3 text-[12.5px] ${d.loopback ? "border-ember-400/50 bg-ember-50" : "border-line bg-paper"}`}>
                <div className="flex items-center gap-1.5 font-semibold"><ShieldCheck className="h-4 w-4" /> Sends you back to <span className="num">{d.redirect_host}</span></div>
                {d.loopback
                  ? <div className="mt-1 text-ink-soft">That is a program on your own computer (for example Claude Code). Only allow it if you just started connecting from there.</div>
                  : <div className="mt-1 text-ink-soft">Only allow this if you just started connecting from {d.client_name}.</div>}
              </div>
              {decide.isError && <div className="mt-3 text-[13px] text-fit-gap-ink">{(decide.error as Error).message}</div>}
              <div className="mt-6 flex gap-2">
                <button className="btn-primary flex-1" disabled={decide.isPending} onClick={() => decide.mutate(true)}>{decide.isPending && <Spinner />} Allow</button>
                <button className="btn-outline flex-1" disabled={decide.isPending} onClick={() => decide.mutate(false)}>Decline</button>
              </div>
              <p className="mt-4 text-[12px] text-ink-muted">You can disconnect it any time in Settings → AI assistants.</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
