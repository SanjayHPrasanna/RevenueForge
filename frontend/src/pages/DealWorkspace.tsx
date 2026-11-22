import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Check, ChevronDown, Download, EyeOff, Info, LayoutGrid, Mail, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Modal, PageLoader, Spinner, StageStatus, useToast } from "../components/ui";
import { useAuthConfig } from "../components/GoogleButton";
import { ApiError, api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ENGAGEMENT, money, plural, STAGES } from "../lib/format";
import { DealStatus } from "./Dashboard";
import { prefetchStages } from "../lib/prefetch";
import { DueDate, LeftToFix, OwnerPicker, ReviewNotes } from "../components/review";
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
  const done = deal.status !== "processing";
  const { data: reqs } = useQuery({ queryKey: ["reqs", deal.id], queryFn: () => api.get<any[]>(`/deals/${deal.id}/requirements`), enabled: done });
  const { data: est } = useQuery({ queryKey: ["stage", deal.id, "estimation"], queryFn: () => api.get(`/deals/${deal.id}/stages/estimation`), enabled: done });
  const { data: arch } = useQuery({ queryKey: ["stage", deal.id, "architecture"], queryFn: () => api.get(`/deals/${deal.id}/stages/architecture`), enabled: done });
  const n = (k: string) => reqs?.filter((r) => r.match_status === k).length || 0;
  const gaps = reqs ? n("gap") : undefined;
  const partial = n("partial");
  const answers = reqs?.filter((r) => r.response).length;
  const high = reqs?.filter((r) => r.gap?.risk === "High").length || 0;
  const mandatory = reqs?.filter((r) => r.priority === "Mandatory").length;
  const e = (est as any)?.data;
  const a = (arch as any)?.data;
  const toHire = e?.team ? e.team.reduce((t: number, r: any) => t + (r.unfilled || 0), 0) : 0;
  return {
    reqs, est: e, gaps,
    metric: {
      overview: "",
      requirements: deal.requirement_count ? `${deal.requirement_count} found` : "",
      matching: deal.coverage_pct != null ? `${deal.coverage_pct}% covered` : "",
      gaps: gaps == null ? "" : gaps ? `${gaps} gap${gaps === 1 ? "" : "s"}` : partial ? `${partial} to mitigate` : "No gaps",
      architecture: a?.layers?.length ? plural(a.layers.length, "layer") : "",
      estimation: e?.headcount ? plural(e.headcount, "person", "people") : "",
      pricing: deal.value ? money(deal.value, deal.value_currency) : "",
      proposal: answers ? `${answers} answers` : "",
      handoff: "",
    } as Record<string, string>,
    sub: {
      requirements: mandatory != null ? `${mandatory} mandatory` : "",
      matching: reqs ? `${n("strong")} strong · ${partial} partial` : "",
      gaps: reqs ? (high ? `${high} high risk` : "No high-risk gaps") : "",
      architecture: a?.choices?.length ? plural(a.choices.length, "technology choice") : "Layers and technology choices",
      estimation: e ? `${e.contract_months || e.duration_months} months${toHire ? ` · ${toHire} to hire` : ""}` : "",
      pricing: deal.margin_pct != null ? `${deal.margin_pct}% margin` : "",
      proposal: "Summary, answers, compliance matrix",
      handoff: "Scope, team, risks, first 30 days",
    } as Record<string, string>,
  };
}

type StageState = "overview" | "approved" | "running" | "draft" | "pending";
function stageState(deal: any, key: string): StageState {
  if (key === "overview") return "overview";
  if (deal.status === "processing" && deal.progress?.stage === key) return "running";
  return (deal.stages.find((s: any) => s.stage === key)?.status || "pending") as StageState;
}

function StatusChip({ deal, k }: { deal: any; k: string }) {
  const st = stageState(deal, k);
  const info = deal.stages.find((s: any) => s.stage === k);
  const by = info?.approved_by ? ` by ${info.approved_by.split(" ")[0]}` : "";
  const [cls, label] = st === "approved" ? ["bg-ok/[.14] text-ok", `Approved${by}`] : st === "running" ? ["bg-ember-500/15 text-ember-600", "Working…"]
    : st === "draft" ? ["bg-brand-500/15 text-brand-700", "Ready to review"] : ["bg-ink/[.07] text-ink-muted", "Waiting"];
  return <span className={clsx("chip", cls)}>{label}</span>;
}

/** Inside a stage: the eight steps in one slim line, no scrolling. */
function StageStrip({ deal, current, onPick }: { deal: any; current: string; onPick: (s: string) => void }) {
  const items = [{ key: "overview", short: "Overview" }, ...STAGES];
  return (
    <nav aria-label="Deal stages" className="glass rounded-[18px] p-1.5 flex flex-wrap gap-1">
      {items.map((s, i) => {
        const active = current === s.key;
        const st = stageState(deal, s.key);
        const notes = deal.stages.find((x: any) => x.stage === s.key)?.open_notes || 0;
        return (
          <button key={s.key} onClick={() => onPick(s.key)} aria-current={active ? "page" : undefined}
            className={clsx("flex-1 min-w-[96px] h-9 rounded-[12px] px-2.5 inline-flex items-center justify-center gap-2 text-[12.5px] font-semibold whitespace-nowrap transition-colors duration-200",
              active ? "bg-brand-500 text-white shadow-btn" : "text-ink-soft hover:bg-ink/[.06] hover:text-ink")}>
            <StepGlyph status={st} n={i} active={active} />
            {s.short}
            {notes > 0 && <span className="rounded-full bg-ember-500 text-white px-1.5 text-[10px] font-bold" title={`${notes} review notes to fix`}>{notes}</span>}
          </button>
        );
      })}
    </nav>
  );
}

/** On the overview: the overview card on top, then the eight stages as two rows of four big cards. */
function StageGrid({ deal, metric, sub, onPick }: { deal: any; metric: Record<string, string>; sub: Record<string, string>; onPick: (s: string) => void }) {
  const approved = deal.stages.filter((s: any) => s.status === "approved").length;
  const bad = deal.verdict === "No bid";
  return (
    <section aria-label="Deal stages">
      <div className="flex items-center justify-between mb-3 px-0.5">
        <h2 className="text-[15px] font-semibold">Deal stages</h2>
        <div className="flex items-center gap-3 text-[12.5px] text-ink-muted">
          <span className="num">{approved} of 8 approved</span>
          <span className="w-40 h-1.5 rounded-full bg-ink/[.1] overflow-hidden"><span className="block h-full bg-brand-500 rounded-full transition-all duration-500" style={{ width: `${(approved / 8) * 100}%` }} /></span>
        </div>
      </div>
      <button onClick={() => onPick("overview")} className="card w-full text-left px-6 py-5 flex flex-wrap items-center gap-4 shadow-[inset_0_0_0_1.5px_rgb(var(--b500)/.7),var(--shadow)]">
        <span className="h-11 w-11 rounded-[14px] grid place-items-center bg-brand-500/15 text-brand-600"><LayoutGrid className="h-5 w-5" /></span>
        <span className="min-w-0">
          <span className="block text-[16px] font-semibold">Overview</span>
          <span className="block text-[13px] text-ink-muted mt-0.5">Coverage map, bid decision, how the client scores bids</span>
        </span>
        {deal.verdict && (
          <span className="ml-auto text-right max-w-[52ch] flex flex-col items-end">
            <span className={clsx("block text-[18px] font-semibold", bad ? "text-fit-gap-ink" : deal.verdict === "Can't assess" ? "text-ink-muted" : "text-ink")}>{deal.verdict}</span>
            {deal.verdict_reason && <span className="text-[12.5px] text-ink-muted mt-0.5 line-clamp-2" title={deal.verdict_reason}>{deal.verdict_reason}</span>}
          </span>
        )}
      </button>
      {[STAGES.slice(0, 4), STAGES.slice(4)].map((row, r) => (
        <div key={r} className="grid grid-cols-2 xl:grid-cols-4 gap-4 mt-4">
          {row.map((s, j) => {
            const i = r * 4 + j + 1;
            const st = stageState(deal, s.key);
            const notes = deal.stages.find((x: any) => x.stage === s.key)?.open_notes || 0;
            const red = (s.key === "matching" && deal.coverage_pct === 0);
            return (
              <button key={s.key} onClick={() => onPick(s.key)} className="card card-hover text-left px-5 pt-4 pb-4 min-h-[148px] flex flex-col">
                <span className="flex items-center gap-2.5">
                  <StepGlyph status={st} n={i} big />
                  <span className="text-[15px] font-semibold truncate">{s.label}</span>
                  {notes > 0 && <span className="ml-auto chip bg-ember-500/15 text-ember-600" title="Review notes to fix">{notes} to fix</span>}
                </span>
                <span className={clsx("block text-[22px] font-semibold tracking-[-0.01em] mt-3.5 leading-tight num", red && "text-fit-gap-ink")}>{metric[s.key] || (st === "pending" ? "—" : "Ready")}</span>
                <span className="block text-[12px] text-ink-muted mt-0.5 truncate">{sub[s.key]}</span>
                <span className="mt-auto pt-3 flex items-center justify-between gap-2 text-[12px] text-ink-muted">
                  <span>{s.role}</span>
                  <StatusChip deal={deal} k={s.key} />
                </span>
              </button>
            );
          })}
        </div>
      ))}
    </section>
  );
}

function StepGlyph({ status, n, active = false, big = false }: { status: StageState; n: number; active?: boolean; big?: boolean }) {
  const size = big ? "h-7 w-7 rounded-[9px] text-[12px]" : "h-[18px] w-[18px] rounded-full text-[10px]";
  if (status === "overview") return <LayoutGrid className={clsx(big ? "h-5 w-5" : "h-4 w-4", active ? "text-white" : "text-brand-600")} aria-hidden />;
  if (status === "approved") return <span className={clsx(size, "bg-ok text-white grid place-items-center shrink-0")} aria-label="Approved"><Check className={big ? "h-3.5 w-3.5" : "h-2.5 w-2.5"} strokeWidth={3.5} /></span>;
  if (status === "running") return <Spinner className={clsx(big ? "h-6 w-6" : "h-4 w-4", "text-ember-500 shrink-0")} />;
  return (
    <span className={clsx(size, "grid place-items-center font-bold num shrink-0",
      active ? "bg-white/20 text-white" : status === "draft" ? "text-brand-700 shadow-[inset_0_0_0_1.5px_rgb(var(--b500)/.6)]" : "text-ink-faint shadow-[inset_0_0_0_1.5px_rgb(var(--line)/.25)]")}
      aria-label={status === "draft" ? "Ready to review" : "Waiting"}>{n}</span>
  );
}

/** The four numbers that matter, as tiles: today's readiness first, so the honest figure is the one people see. */
function HeadlineTiles({ deal, est, gaps }: { deal: any; est: any; gaps?: number }) {
  if (deal.readiness == null) return null;
  const empty = deal.verdict === "Can't assess";
  const low = deal.readiness < 35;
  const tiles = [
    { cls: low ? "kpi-gap" : "kpi-1", label: "Readiness today", value: empty ? "—" : `${deal.readiness}%`, tone: low && !empty ? "text-fit-gap-ink" : "",
      sub: empty ? "Knowledge library is empty: nothing to match" : `${deal.mitigated_readiness}% only if the mitigation plan works` },
    { cls: "kpi-1", label: "Price", value: deal.value ? money(deal.value, deal.value_currency) : "—", tone: "",
      sub: empty ? "Estimate from market benchmark rates" : deal.margin_pct != null ? `${deal.margin_pct}% margin` : "" },
    { cls: "kpi-2", label: "Team", value: est?.headcount ? plural(est.headcount, "person", "people") : "—", tone: "",
      sub: est ? `${est.contract_months || est.duration_months} months${deal.engagement_type ? ` · ${(ENGAGEMENT[deal.engagement_type] || "").toLowerCase()}` : ""}` : "" },
    { cls: "kpi-4", label: "Requirements", value: String(deal.requirement_count ?? "—"), tone: "",
      sub: [gaps != null ? plural(gaps, "gap") : "", deal.coverage_pct != null ? `${deal.coverage_pct}% covered` : ""].filter(Boolean).join(" · ") },
  ];
  return (
    <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 mt-6">
      {tiles.map((t) => (
        <div key={t.label} className={clsx("card px-5 pt-4 pb-4 min-h-[108px] flex flex-col", t.cls)}>
          <div className="text-[12.5px] font-semibold text-ink-muted">{t.label}</div>
          <div className={clsx("num text-[24px] font-semibold tracking-[-0.01em] mt-2 leading-tight", t.tone)}>{t.value}</div>
          <div className="text-[12px] text-ink-muted mt-auto pt-1.5 leading-snug">{t.sub}</div>
        </div>
      ))}
    </div>
  );
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
        <div className="font-bold text-[15px]">{p.message || "Working on it"}</div>
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
          <span className="h-8 w-8 shrink-0 rounded-lg bg-surface border border-brand-100 grid place-items-center text-brand-600"><Mail className="h-4 w-4" aria-hidden /></span>
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
  const qc = useQueryClient();
  const ready = deal && (deal as any).status !== "processing";
  useEffect(() => { if (ready && id) prefetchStages(qc, id); }, [ready, id]);
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
    mutationFn: async () => {
      try {
        return await api.post(`/deals/${id}/stages/${stage}/approve`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && /cost line/.test(e.message)) {
          throw new Error(e.message);  // partner, licence and commitment lines need a real or confirmed figure: no bypass
        }
        if (e instanceof ApiError && e.status === 409 && /Mandatory eligibility not met/.test(e.message)) {
          const reason = prompt(`${e.message}\n\nWhy bid anyway? (recorded in the audit log)`)?.trim() || "";
          if (reason.length < 10) throw new Error("Not approved: a reason of at least 10 characters is needed to bid past a failed eligibility condition.");
          return api.post(`/deals/${id}/stages/${stage}/approve`, { despite_failed_gates: true, gate_override_reason: reason, despite_open_notes: true });
        }
        if (e instanceof ApiError && e.status === 409 && confirm(`${e.message}\n\nApprove this stage anyway?`)) {
          return api.post(`/deals/${id}/stages/${stage}/approve`, { despite_open_notes: true, despite_over_budget: true, despite_validation: true });
        }
        if (e instanceof ApiError && e.status === 409) throw new Error("Not approved.");
        throw e;
      }
    },
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
    <div className="px-4 lg:px-6 py-6 max-w-[1480px]">
      <Link to="/app/deals" className="text-[13px] text-ink-muted hover:text-ink inline-flex items-center gap-1"><ArrowLeft className="h-3.5 w-3.5" /> Deals</Link>
      <div className="mt-3 flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="min-w-[min(100%,30rem)] flex-1">
          <div className="flex items-start gap-3">
            <h1 className="min-w-0 font-display font-semibold text-[26px] md:text-[30px] leading-[1.1] tracking-[-0.02em] text-ink">{deal.name}</h1>
            <span className="shrink-0 mt-2"><DealStatus s={deal.status} /></span>
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13.5px] text-ink-muted">
            {[
              <span key="c" className="inline-flex items-center gap-1.5 font-semibold text-ink-soft" title={deal.confidential ? "Client name masked" : undefined}>{deal.confidential && <EyeOff className="h-3.5 w-3.5" />}{deal.client}</span>,
              deal.doc_type && <span key="d">{deal.doc_type}</span>,
              deal.engagement_type && <span key="e">{ENGAGEMENT[deal.engagement_type]}</span>,
              deal.industry && <span key="i">{deal.industry}</span>,
              deal.region && <span key="r">{deal.region}</span>,
              <DueDate key="due" deal={deal} />,
            ].filter(Boolean).flatMap((el, i) => (i ? [<span key={`s${i}`} className="text-ink-faint" aria-hidden>·</span>, el] : [el]))}
          </div>
        </div>
        <div className="flex items-center gap-2 relative">
          <OwnerPicker deal={deal} compact />
          <button className="btn-outline" onClick={() => setMenu(menu === "dl" ? null : "dl")} disabled={processing}><Download className="h-4 w-4" /> Download <ChevronDown className="h-3.5 w-3.5" /></button>
          <button className="btn-outline" aria-haspopup="menu" aria-expanded={menu === "outcome"} onClick={() => setMenu(menu === "outcome" ? null : "outcome")}>Outcome <ChevronDown className="h-3.5 w-3.5" /></button>
          {menu === "dl" && (
            <div className="absolute right-24 top-10 z-20 card shadow-lift w-72 py-1 text-sm" onMouseLeave={() => setMenu(null)}>
              {[["proposal", "Proposal (.docx)"], ["proposal_pack", "Proposal + solution video (.zip)"], ["story", "Solution video (.mp4)"], ["handoff", "Delivery handoff (.docx)"], ["requirements", "Requirements & compliance (.xlsx)"]].map(([k, l]) => (
                <button key={k} className="w-full text-left px-3 py-2 hover:bg-paper" onClick={() => { setMenu(null); download(`/deals/${id}/download/${k}`, `${k}`).catch((e) => toast("error", e.message)); }}>{l}</button>
              ))}
            </div>
          )}
          {menu === "outcome" && (
            <div role="menu" aria-label="Outcome" className="absolute right-0 top-10 z-20 card shadow-lift w-56 py-1 text-sm" onMouseLeave={() => setMenu(null)}>
              {[["submitted", "Mark as submitted"], ["won", "Mark as won"], ["lost", "Mark as lost"], ["no_bid", "Decided not to bid"]].map(([k, l]) => (
                <button key={k} role="menuitem" className="w-full text-left px-3 py-2 hover:bg-paper" onClick={() => {
                  setMenu(null);
                  if (k === "won" || k === "lost") {
                    update.reset();
                    setOutcome({ status: k, final_value: deal.final_value ? String(deal.final_value) : "", actual_effort_days: "", outcome_notes: deal.outcome_notes || "" });
                  } else update.mutate({ status: k });
                }}>{l}</button>
              ))}
              <div className="border-t border-line-soft my-1" />
              <button role="menuitem" className="w-full text-left px-3 py-2 hover:bg-paper flex items-center gap-2" onClick={() => { setMenu(null); rerun.mutate("requirements"); }}><RefreshCw className="h-3.5 w-3.5" /> Re-run from the start</button>
              <button role="menuitem" className="w-full text-left px-3 py-2 hover:bg-paper text-fit-gap-ink flex items-center gap-2" onClick={() => confirm("Delete this deal and its outputs? This can't be undone.") && del.mutate()}><Trash2 className="h-3.5 w-3.5" /> Delete deal</button>
            </div>
          )}
        </div>
      </div>

      <Modal open={!!outcome} onClose={() => setOutcome(null)} title={outcome?.status === "won" ? "Record a win" : "Record a loss"}>
        {outcome && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); update.mutate({ status: outcome.status, final_value: outcome.final_value || 0, outcome_notes: outcome.outcome_notes, ...(outcome.actual_effort_days ? { actual_effort_days: outcome.actual_effort_days } : {}) }, { onSuccess: () => setOutcome(null) }); }}>
            <p className="text-[13px] text-ink-muted">RevenueForge learns from outcomes: answers from wins rank higher, and actual effort calibrates future estimates.</p>
            {outcome.status === "won" && (
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label">Contract value ({deal.value_currency || "USD"})</label><input className="input num" type="number" value={outcome.final_value} onChange={(e) => setOutcome({ ...outcome, final_value: e.target.value })} /></div>
                <div><label className="label">Actual effort (person-days)</label><input className="input num" type="number" placeholder="After delivery" value={outcome.actual_effort_days} onChange={(e) => setOutcome({ ...outcome, actual_effort_days: e.target.value })} /></div>
              </div>
            )}
            <div><label className="label">{outcome.status === "won" ? "Why we won" : "Why we lost"}</label><textarea className="input h-20 py-2" value={outcome.outcome_notes} onChange={(e) => setOutcome({ ...outcome, outcome_notes: e.target.value })} placeholder={outcome.status === "won" ? "e.g. strongest references, best transition plan" : "e.g. price, missing certification"} /></div>
            {update.isError && <div role="alert" className="text-[13px] text-fit-gap-ink">{(update.error as any)?.message}</div>}
            <button className="btn-primary" disabled={update.isPending}>Save outcome</button>
          </form>
        )}
      </Modal>

      <HeadlineTiles deal={deal} est={m.est} gaps={m.gaps} />

      <div className="mt-8">
        {stage === "overview" && !processing
          ? <StageGrid deal={deal} metric={m.metric} sub={m.sub} onPick={(s) => nav(`/app/deals/${id}/${s === "overview" ? "" : s}`)} />
          : <StageStrip deal={deal} current={stage} onPick={(s) => nav(`/app/deals/${id}/${s === "overview" ? "" : s}`)} />}
      </div>

      {deal.status === "failed" && (
        <div className="card mt-4 p-4 border-fit-gap/30 flex flex-wrap items-center gap-3 text-sm">
          <span className="text-fit-gap-ink font-semibold">{deal.progress?.message || "Processing stopped."}</span>
          <div className="flex-1" />
          <button className="btn-primary" onClick={() => rerun.mutate(deal.progress?.stage || "requirements")}>Try again</button>
        </div>
      )}

      {processing && (stage === "overview" || (stageInfo?.status !== "draft" && stageInfo?.status !== "approved")) ? (
        <Processing deal={deal} />
      ) : stage === "overview" ? (
        <div className="mt-8"><LeftToFix deal={deal} /><OverviewStage deal={deal} /></div>
      ) : (
        <div className="mt-6">
          <div className="glass rounded-2xl px-5 py-3.5 flex flex-wrap items-center gap-3 mb-4">
            <span className="h-7 w-7 rounded-[9px] grid place-items-center bg-brand-500 text-white text-[12px] font-bold num">{STAGES.findIndex((s) => s.key === stage) + 1}</span>
            <h2 className="text-[17px] font-semibold tracking-[-0.01em]">{STAGES.find((s) => s.key === stage)?.label}</h2>
            <StatusChip deal={deal} k={stage} />
            <span className="text-ink-faint cursor-help" title={STAGE_HELP[stage]} aria-label={STAGE_HELP[stage]}><Info className="h-4 w-4" /></span>
            <div className="flex-1" />
            {stageInfo?.status === "draft" && (
              <button className="btn-primary" disabled={!canApprove || approve.isPending} onClick={() => approve.mutate()} title={canApprove ? "" : `Needs the ${APPROVER[stage].join(" or ")} role`}>
                {approve.isPending ? <Spinner /> : <Check className="h-4 w-4" />} Approve {STAGES.find((s) => s.key === stage)?.short.toLowerCase()}
              </button>
            )}
          </div>
          <ReviewNotes deal={deal} stage={stage} />
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
