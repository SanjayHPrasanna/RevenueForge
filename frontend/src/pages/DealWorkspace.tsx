import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Check, ChevronDown, Download, EyeOff, Mail, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Modal, PageLoader, Spinner, StageStatus, useToast } from "../components/ui";
import { useAuthConfig } from "../components/GoogleButton";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ENGAGEMENT, money, STAGES } from "../lib/format";
import { DealStatus } from "./Dashboard";
import { OverviewStage } from "./Overview";
import { ArchitectureStage, EstimationStage, GapsStage, HandoffStage, MatchingStage, PricingStage, ProposalStage, RequirementsStage } from "./stages";

const STAGE_HELP: Record<string, string> = {
  requirements: "Check that every obligation in the RFP was found and sorted into the right category. Select a row to see it highlighted in the source.",
  matching: "Check each requirement against the evidence found in your library. Change a match when you know better; RevenueForge learns from it.",
  gaps: "Decide how each gap will be closed. The bid recommendation updates from the plan.",
  architecture: "Check the solution layers and the technology choices, each traced to the requirements that drove it.",
  estimation: "Check the plan, the team and the effort. Change the term, onsite share or contingency and everything downstream recalculates.",
  pricing: "Pick the price that goes into the proposal. Every option is shown against your cost and your margin floor.",
  proposal: "Read the executive summary and edit any answer. Your edits are kept and learned from.",
  handoff: "Check what delivery inherits: scope, team, risks and the first 30 days.",
};

const APPROVER: Record<string, string[]> = {
  requirements: ["presales"], matching: ["presales", "architect"], gaps: ["presales", "architect"], architecture: ["architect"],
  estimation: ["architect", "delivery"], pricing: ["finance"], proposal: ["presales"], handoff: ["delivery", "presales"],
};

function useMetrics(deal: any) {
  const { data: reqs } = useQuery({ queryKey: ["reqs", deal.id], queryFn: () => api.get<any[]>(`/deals/${deal.id}/requirements`), enabled: deal.status !== "processing" });
  const { data: est } = useQuery({ queryKey: ["stage", deal.id, "estimation"], queryFn: () => api.get(`/deals/${deal.id}/stages/estimation`), enabled: deal.status !== "processing" });
  const gaps = reqs?.filter((r) => r.match_status === "gap").length;
  const answers = reqs?.filter((r) => r.response).length;
  const e = (est as any)?.data;
  return {
    reqs, est: e,
    metric: {
      overview: "",
      requirements: deal.requirement_count ? `${deal.requirement_count} found` : "",
      matching: deal.coverage_pct != null ? `${deal.coverage_pct}% covered` : "",
      gaps: gaps != null ? `${gaps} gap${gaps === 1 ? "" : "s"}` : "",
      architecture: "",
      estimation: e?.headcount ? `${e.headcount} people` : "",
      pricing: deal.value ? money(deal.value, deal.value_currency) : "",
      proposal: answers ? `${answers} answers` : "",
      handoff: "",
    } as Record<string, string>,
  };
}

function StageRail({ deal, current, metric, onPick }: { deal: any; current: string; metric: Record<string, string>; onPick: (s: string) => void }) {
  const st = Object.fromEntries(deal.stages.map((s: any) => [s.stage, s]));
  const runningStage = deal.status === "processing" ? deal.progress?.stage : null;
  const items = [{ key: "overview", label: "Overview", short: "Overview", role: "" }, ...STAGES];
  return (
    <nav aria-label="Deal stages" className="overflow-x-auto scroll-thin -mx-4 px-4 lg:-mx-8 lg:px-8 border-b border-line">
      <ol className="flex min-w-max">
        {items.map((s, i) => {
          const status = s.key === "overview" ? "overview" : runningStage === s.key ? "running" : st[s.key]?.status || "pending";
          const active = current === s.key;
          return (
            <li key={s.key} className="flex-none">
              <button onClick={() => onPick(s.key)} aria-current={active ? "page" : undefined}
                className={clsx("w-full text-left px-3 pt-2.5 pb-3 border-b-2 -mb-px rounded-t-xl transition-all duration-200 ease-apple",
                  active ? "border-brand-950 bg-white/80 shadow-[0_-6px_18px_-12px_rgba(8,43,61,.35)]" : "border-transparent hover:border-line hover:bg-white/50")}>
                <span className="flex items-center gap-1.5">
                  <StepGlyph status={status} n={i} />
                  <span className={clsx("text-[13px] whitespace-nowrap", active ? "font-bold text-ink" : "font-medium text-ink-soft")}>
                    <span className="min-[1400px]:hidden">{s.short}</span><span className="hidden min-[1400px]:inline">{s.label}</span>
                  </span>
                </span>
                <span className={clsx("block text-[11.5px] mt-0.5 pl-[22px] whitespace-nowrap num", status === "pending" ? "text-ink-faint" : "text-ink-muted")}>
                  {status === "running" ? "Working…" : status === "approved" ? `Approved${st[s.key]?.approved_by ? ` by ${st[s.key].approved_by.split(" ")[0]}` : ""}` : metric[s.key] || (status === "pending" ? "Waiting" : status === "overview" ? "" : "Ready to review")}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function StepGlyph({ status, n }: { status: string; n: number }) {
  if (status === "overview") return <span className="h-4 w-4 grid grid-cols-2 gap-[2px] shrink-0" aria-hidden>{[0, 1, 2, 3].map((i) => <span key={i} className="rounded-[1.5px] bg-brand-800" />)}</span>;
  if (status === "approved") return <span className="h-4 w-4 rounded-full bg-ok text-white grid place-items-center shrink-0" aria-label="Approved"><Check className="h-2.5 w-2.5" strokeWidth={3.5} /></span>;
  if (status === "running") return <Spinner className="h-4 w-4 text-ember-500 shrink-0" />;
  return (
    <span className={clsx("h-4 w-4 rounded-full grid place-items-center text-[9.5px] font-bold num shrink-0 border-[1.5px]",
      status === "draft" ? "border-brand-500 text-brand-700 bg-white" : "border-line text-ink-faint bg-white")} aria-label={status === "draft" ? "Ready to review" : "Waiting"}>{n}</span>
  );
}

function Standfirst({ deal, est }: { deal: any; est: any }) {
  if (deal.readiness == null) return null;
  const parts: string[] = [];
  parts.push(`${deal.requirement_count} requirements found.`);
  parts.push(`Bid readiness is ${deal.readiness}% today and ${deal.mitigated_readiness}% with the mitigation plan.`);
  if (deal.value) {
    let s = `Priced at ${money(deal.value, deal.value_currency)} with a ${deal.margin_pct}% margin`;
    if (est?.headcount) s += `, delivered by ${est.headcount} people over ${est.contract_months || est.duration_months} months`;
    parts.push(s + ".");
  }
  return <p className="font-display text-[17px] md:text-[19px] leading-snug text-ink-soft mt-3 max-w-[72ch]">{parts.join(" ")}</p>;
}

function Processing({ deal }: { deal: any }) {
  const { user } = useAuth();
  const { data: cfg } = useAuthConfig();
  const p = deal.progress || {};
  const idx = Math.max(0, STAGES.findIndex((s) => s.key === p.stage));
  return (
    <div className="card p-6 md:p-8 my-6">
      <div className="flex items-center gap-3">
        <Spinner className="h-5 w-5 text-ember-500" />
        <div className="font-bold text-[17px]">{p.message || "Working on it"}</div>
        <div className="flex-1" />
        <div className="num text-ink-muted text-sm">{p.pct ?? 0}%</div>
      </div>
      <div className="h-1.5 bg-line-soft rounded-full mt-4 overflow-hidden">
        <div className="h-full bg-ember-500 rounded-full transition-all duration-700" style={{ width: `${Math.max(4, p.pct || 0)}%` }} />
      </div>
      <ol className="mt-5 grid sm:grid-cols-2 lg:grid-cols-4 gap-2 text-[13px]">
        {STAGES.map((s, i) => (
          <li key={s.key} className={clsx("flex items-center gap-2", i < idx ? "text-ok" : i === idx ? "text-ink font-semibold" : "text-ink-faint")}>
            {i < idx ? <Check className="h-4 w-4" /> : i === idx ? <Spinner className="h-3.5 w-3.5" /> : <span className="h-4 w-4 grid place-items-center">·</span>}
            {s.label}
          </li>
        ))}
      </ol>
      {cfg?.email_notifications && user?.email && (
        <div className="mt-6 flex items-start gap-3 rounded-xl bg-brand-50/70 border border-brand-100 px-4 py-3 text-[13.5px] text-ink-soft">
          <span className="h-8 w-8 shrink-0 rounded-lg bg-white border border-brand-100 grid place-items-center text-brand-600"><Mail className="h-4 w-4" aria-hidden /></span>
          <div>
            <div className="font-semibold text-ink">I’ll email you when it’s ready for review</div>
            <div className="mt-0.5">We’ll send a note to <span className="font-semibold text-ink">{user.email}</span>, so you can close this page and come back later.</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function DealWorkspace() {
  const { id, stage = "overview" } = useParams();
  const { data: deal, isLoading } = useQuery({
    queryKey: ["deal", id],
    queryFn: () => api.get(`/deals/${id}`),
    refetchInterval: (q) => ((q.state.data as any)?.status === "processing" ? 1200 : false),
  });
  if (isLoading || !deal) return <PageLoader />;
  return <Workspace deal={deal} stage={stage} />;
}

function Workspace({ deal, stage }: { deal: any; stage: string }) {
  const id = deal.id;
  const nav = useNavigate();
  const { user } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const m = useMetrics(deal);
  const [menu, setMenu] = useState<"dl" | "outcome" | null>(null);
  const [outcome, setOutcome] = useState<null | { status: string; final_value: string; actual_effort_days: string; outcome_notes: string }>(null);
  const approve = useMutation({
    mutationFn: () => api.post(`/deals/${id}/stages/${stage}/approve`),
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["deal", id] });
      const L = r?.learned || {};
      const extra = L.classifier ? (L.classifier.status === "trained" ? ` Your classifier retrained (${L.classifier.cv_accuracy ?? "—"}% accuracy).` : ` ${L.classifier.examples}/${L.classifier.needed} reviewed requirements toward your own classifier.`)
        : L.answers_added != null ? ` ${L.answers_added} answers added to your library.` : "";
      toast("ok", `${STAGES.find((s) => s.key === stage)?.label} approved.${extra}`);
      const i = STAGES.findIndex((s) => s.key === stage);
      if (i < STAGES.length - 1) nav(`/app/deals/${id}/${STAGES[i + 1].key}`);
    },
    onError: (e: any) => toast("error", e.message),
  });
  const update = useMutation({
    mutationFn: (body: any) => api.patch(`/deals/${id}`, body),
    onSuccess: () => { qc.invalidateQueries(); setMenu(null); toast("ok", "Deal updated."); },
    onError: (e: any) => toast("error", e.message),
  });
  const rerun = useMutation({
    mutationFn: (from: string) => api.post(`/deals/${id}/rerun`, { from_stage: from }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["deal", id] }),
    onError: (e: any) => toast("error", e.message),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/deals/${id}`),
    onSuccess: () => { qc.invalidateQueries(); nav("/app/deals"); },
  });
  const processing = deal.status === "processing";
  const stageInfo = deal.stages.find((s: any) => s.stage === stage);
  const canApprove = user && stage !== "overview" && (user.role === "admin" || APPROVER[stage]?.includes(user.role));
  const props = { deal, stage, onChanged: () => qc.invalidateQueries({ queryKey: ["deal", id] }) };

  return (
    <div className="px-4 lg:px-8 py-5 max-w-[1500px]">
      <Link to="/app/deals" className="text-[13px] text-ink-muted hover:text-ink inline-flex items-center gap-1"><ArrowLeft className="h-3.5 w-3.5" /> Deals</Link>
      <div className="mt-2 flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="min-w-[min(100%,30rem)] flex-1">
          <h1 className="font-display text-[30px] md:text-[42px] leading-[1.04] tracking-[-0.025em] text-brand-950">{deal.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-ink-muted">
            <span className="inline-flex items-center gap-1.5 font-semibold text-ink-soft" title={deal.confidential ? "Client name masked" : undefined}>{deal.confidential && <EyeOff className="h-3.5 w-3.5" />}{deal.client}</span>
            <span>{deal.doc_type}</span>
            {deal.engagement_type && <span>{ENGAGEMENT[deal.engagement_type]}</span>}
            {deal.industry && <span>{deal.industry}{deal.sector ? `, ${deal.sector.toLowerCase()} sector` : ""}</span>}
            {deal.region && <span>{deal.region}</span>}
            {deal.due_date && <span>Due {deal.due_date}</span>}
            <DealStatus s={deal.status} />
          </div>
          <Standfirst deal={deal} est={m.est} />
        </div>
        <div className="flex gap-2 relative">
          <button className="btn-outline" onClick={() => setMenu(menu === "dl" ? null : "dl")} disabled={processing}><Download className="h-4 w-4" /> Download <ChevronDown className="h-3.5 w-3.5" /></button>
          <button className="btn-outline" onClick={() => setMenu(menu === "outcome" ? null : "outcome")}>Outcome <ChevronDown className="h-3.5 w-3.5" /></button>
          {menu === "dl" && (
            <div className="absolute right-24 top-10 z-20 card shadow-lift w-72 py-1 text-sm" onMouseLeave={() => setMenu(null)}>
              {[["proposal", "Proposal (.docx)"], ["proposal_pack", "Proposal + solution video (.zip)"], ["story", "Solution video (.mp4)"], ["handoff", "Delivery handoff (.docx)"], ["requirements", "Requirements & compliance (.xlsx)"]].map(([k, l]) => (
                <button key={k} className="w-full text-left px-3 py-2 hover:bg-paper" onClick={() => { setMenu(null); download(`/deals/${id}/download/${k}`, `${k}`).catch((e) => toast("error", e.message)); }}>{l}</button>
              ))}
            </div>
          )}
          {menu === "outcome" && (
            <div className="absolute right-0 top-10 z-20 card shadow-lift w-56 py-1 text-sm" onMouseLeave={() => setMenu(null)}>
              {[["submitted", "Mark as submitted"], ["won", "Mark as won"], ["lost", "Mark as lost"], ["no_bid", "Decided not to bid"]].map(([k, l]) => (
                <button key={k} className="w-full text-left px-3 py-2 hover:bg-paper" onClick={() => {
                  setMenu(null);
                  if (k === "won" || k === "lost") setOutcome({ status: k, final_value: deal.final_value ? String(deal.final_value) : "", actual_effort_days: "", outcome_notes: deal.outcome_notes || "" });
                  else update.mutate({ status: k });
                }}>{l}</button>
              ))}
              <div className="border-t border-line-soft my-1" />
              <button className="w-full text-left px-3 py-2 hover:bg-paper flex items-center gap-2" onClick={() => { setMenu(null); rerun.mutate("requirements"); }}><RefreshCw className="h-3.5 w-3.5" /> Re-run from the start</button>
              <button className="w-full text-left px-3 py-2 hover:bg-paper text-fit-gap-ink flex items-center gap-2" onClick={() => confirm("Delete this deal and its outputs? This can't be undone.") && del.mutate()}><Trash2 className="h-3.5 w-3.5" /> Delete deal</button>
            </div>
          )}
        </div>
      </div>

      <Modal open={!!outcome} onClose={() => setOutcome(null)} title={outcome?.status === "won" ? "Record a win" : "Record a loss"}>
        {outcome && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); update.mutate({ status: outcome.status, final_value: outcome.final_value || 0, outcome_notes: outcome.outcome_notes, ...(outcome.actual_effort_days ? { actual_effort_days: outcome.actual_effort_days } : {}) }); setOutcome(null); }}>
            <p className="text-[13px] text-ink-muted">RevenueForge learns from outcomes: answers from wins rank higher, and actual effort calibrates future estimates.</p>
            {outcome.status === "won" && (
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label">Contract value ({deal.value_currency || "USD"})</label><input className="input num" type="number" value={outcome.final_value} onChange={(e) => setOutcome({ ...outcome, final_value: e.target.value })} /></div>
                <div><label className="label">Actual effort (person-days)</label><input className="input num" type="number" placeholder="After delivery" value={outcome.actual_effort_days} onChange={(e) => setOutcome({ ...outcome, actual_effort_days: e.target.value })} /></div>
              </div>
            )}
            <div><label className="label">{outcome.status === "won" ? "Why we won" : "Why we lost"}</label><textarea className="input h-20 py-2" value={outcome.outcome_notes} onChange={(e) => setOutcome({ ...outcome, outcome_notes: e.target.value })} placeholder={outcome.status === "won" ? "e.g. strongest references, best transition plan" : "e.g. price, missing certification"} /></div>
            <button className="btn-primary">Save outcome</button>
          </form>
        )}
      </Modal>

      <div className="mt-6">
        <StageRail deal={deal} current={stage} metric={m.metric} onPick={(s) => nav(`/app/deals/${id}/${s === "overview" ? "" : s}`)} />
      </div>

      {deal.status === "failed" && (
        <div className="card mt-4 p-4 border-[#F1C4C0] flex flex-wrap items-center gap-3 text-sm">
          <span className="text-fit-gap-ink font-semibold">{deal.progress?.message || "Processing stopped."}</span>
          <div className="flex-1" />
          <button className="btn-primary" onClick={() => rerun.mutate(deal.progress?.stage || "requirements")}>Try again</button>
        </div>
      )}

      {processing && (stage === "overview" || (stageInfo?.status !== "draft" && stageInfo?.status !== "approved")) ? (
        <Processing deal={deal} />
      ) : stage === "overview" ? (
        <div className="mt-6"><OverviewStage deal={deal} /></div>
      ) : (
        <div className="mt-6">
          <div className="flex flex-wrap items-start gap-3 mb-4">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-[20px] font-bold tracking-tight">{STAGES.find((s) => s.key === stage)?.label}</h2>
                {stageInfo && <StageStatus status={stageInfo.status} />}
                {stageInfo?.approved_by && <span className="text-[12.5px] text-ink-muted">by {stageInfo.approved_by}</span>}
              </div>
              <p className="text-[13px] text-ink-muted mt-1 max-w-[80ch]">{STAGE_HELP[stage]}</p>
            </div>
            {stageInfo?.status === "draft" && (
              <button className="btn-primary" disabled={!canApprove || approve.isPending} onClick={() => approve.mutate()} title={canApprove ? "" : `Needs the ${APPROVER[stage].join(" or ")} role`}>
                {approve.isPending ? <Spinner /> : <Check className="h-4 w-4" />} Approve {STAGES.find((s) => s.key === stage)?.short.toLowerCase()}
              </button>
            )}
          </div>
          {stage === "requirements" && <RequirementsStage {...props} />}
          {stage === "matching" && <MatchingStage {...props} />}
          {stage === "gaps" && <GapsStage {...props} />}
          {stage === "architecture" && <ArchitectureStage {...props} />}
          {stage === "estimation" && <EstimationStage {...props} />}
          {stage === "pricing" && <PricingStage {...props} />}
          {stage === "proposal" && <ProposalStage {...props} />}
          {stage === "handoff" && <HandoffStage {...props} />}
        </div>
      )}
    </div>
  );
}
