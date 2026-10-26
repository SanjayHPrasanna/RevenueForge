import { useQuery } from "@tanstack/react-query";
import { ArrowRight, History } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageLoader } from "../components/ui";
import { Bars, CoverageMap, FitLegend, PriceLadder, ReadinessScale, StatusRows, TeamBars, WeightBar } from "../components/viz";
import { api } from "../lib/api";
import { CATEGORIES, ENGAGEMENT, money } from "../lib/format";
import { DealStatus } from "./Dashboard";

const useStage = (id: string, stage: string) => useQuery({ queryKey: ["stage", id, stage], queryFn: () => api.get(`/deals/${id}/stages/${stage}`) });

function Panel({ title, sub, action, children, className = "" }: { title: string; sub?: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card p-5 md:p-6 min-w-0 flex flex-col ${className}`}>
      <div className="flex items-start gap-3 mb-4">
        <div className="min-w-0 flex-1">
          <h3 className="font-bold text-[15.5px] text-ink">{title}</h3>
          {sub && <p className="text-[12.5px] text-ink-muted mt-0.5 leading-snug">{sub}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

const MITIGATION_LABEL: Record<string, string> = {
  Partner: "Bring in a partner", Upskill: "Upskill the team", Hire: "Hire", Certify: "Get certified", Build: "Build it",
  "Strengthen evidence": "Strengthen evidence", "Define method": "Define the method",
};

export function OverviewStage({ deal }: { deal: any }) {
  const nav = useNavigate();
  const { data: reqs } = useQuery({ queryKey: ["reqs", deal.id], queryFn: () => api.get<any[]>(`/deals/${deal.id}/requirements`) });
  const { data: est } = useStage(deal.id, "estimation");
  const { data: pr } = useStage(deal.id, "pricing");

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    (reqs || []).forEach((r) => (c[r.match_status] = (c[r.match_status] || 0) + 1));
    return c;
  }, [reqs]);
  const byCat = useMemo(() => CATEGORIES.map((cat) => {
    const c: Record<string, number> = {};
    (reqs || []).filter((r) => r.category === cat).forEach((r) => (c[r.match_status] = (c[r.match_status] || 0) + 1));
    return { label: cat, counts: c };
  }).filter((r) => Object.keys(r.counts).length), [reqs]);
  const mitigations = useMemo(() => {
    const m: Record<string, number> = {};
    (reqs || []).filter((r) => r.gap?.recommended).forEach((r) => (m[r.gap.recommended] = (m[r.gap.recommended] || 0) + 1));
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }, [reqs]);

  if (!reqs) return <PageLoader />;
  const p = pr?.data;
  const e = est?.data;
  const fx = p?.fx_to_rfp ?? 1;
  const ccy = p?.rfp_currency || deal.value_currency;
  const fmt = (v: number) => money(v * fx, ccy);
  const criteria = (deal.meta?.evaluation_criteria || []).filter((c: any) => c.weight).map((c: any) => ({ label: c.criterion.replace(/:\s*\d+\s*%$/, ""), weight: c.weight }));
  const missing = deal.meta?.top_missing || [];

  const scoring = criteria.length > 0 ? (
    <Panel title="How the client scores bids" sub="Evaluation weights stated in the RFP. Put the effort where the points are.">
      <WeightBar items={criteria} />
    </Panel>
  ) : (
    <Panel title="How the client scores bids" sub="The RFP doesn't state evaluation weights.">
      <p className="text-[13px] text-ink-muted">Ask in the clarification round how technical and commercial scores are weighted.</p>
    </Panel>
  );

  return (
    <div className="space-y-4">
      <div className="grid xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] gap-4 items-start">
        <div className="space-y-4 min-w-0">
          <Panel title="Coverage map" sub="Every requirement in the RFP, in document order, grouped by section. Select a tile to see the evidence."
            action={<Link to={`/app/deals/${deal.id}/matching`} className="text-[13px] font-semibold text-brand-700 hover:underline whitespace-nowrap">Open match</Link>}>
            <FitLegend counts={counts} className="mb-1" />
            <p className="text-[11.5px] text-ink-faint mb-4">Small tiles are desirable rather than mandatory.</p>
            <CoverageMap reqs={reqs} onPick={(r) => nav(`/app/deals/${deal.id}/matching?r=${r.id}`)} />
            <div className="mt-6 pt-5 border-t border-line-soft">
              <div className="flex flex-wrap items-baseline gap-x-3 mb-3"><h4 className="font-semibold text-[14px]">By category</h4><span className="text-[12px] text-ink-muted">Select a bar to filter the match list.</span></div>
              <StatusRows rows={byCat} onPick={(cat, st) => nav(`/app/deals/${deal.id}/matching?cat=${encodeURIComponent(cat)}&status=${st}`)} />
            </div>
          </Panel>
          {scoring}
        </div>

        <div className="space-y-4 min-w-0">
          <Panel title="Bid decision">
            <div className="font-display text-[30px] leading-tight text-brand-950">{deal.verdict || "Not scored yet"}</div>
            {deal.readiness != null && (
              <div className="mt-5">
                <ReadinessScale today={deal.readiness} mitigated={deal.mitigated_readiness ?? deal.readiness} />
                <p className="text-[13px] text-ink-soft mt-3 leading-relaxed">
                  Readiness is <b className="num">{deal.readiness}%</b> with what you have today and <b className="num">{deal.mitigated_readiness}%</b> once the mitigation plan is in place.
                  {deal.coverage_pct != null && <> Your library covers <b className="num">{deal.coverage_pct}%</b> of the mandatory requirements.</>}
                </p>
              </div>
            )}
          </Panel>
          {mitigations.length > 0 && (
            <Panel title="How the plan closes the gaps" sub="Recommended fix for each gap or partial match. Select one to see those requirements."
              action={<Link to={`/app/deals/${deal.id}/gaps`} className="text-[13px] font-semibold text-brand-700 hover:underline whitespace-nowrap">Open gaps</Link>}>
              <Bars rows={mitigations.map(([k, n]) => ({ label: MITIGATION_LABEL[k] || k, value: n }))} format={(v) => `${v}`} color="#0C3D55"
                onPick={(label) => { const k = mitigations.find(([key]) => (MITIGATION_LABEL[key] || key) === label)?.[0]; nav(`/app/deals/${deal.id}/gaps${k ? `?fix=${encodeURIComponent(k)}` : ""}`); }} />
              {missing.length > 0 && (
                <div className="mt-4 pt-4 border-t border-line-soft">
                  <div className="text-[12.5px] text-ink-muted mb-2">Technologies the RFP names that you don't have</div>
                  <div className="flex flex-wrap gap-1.5">{missing.map((m: any) => <span key={m.technology} className="chip bg-[#FBE7E5] text-fit-gap-ink">{m.technology}</span>)}</div>
                </div>
              )}
            </Panel>
          )}
          {e && (
            <Panel title="Team" sub={`${e.headcount} people, ${e.fte} FTE, over ${e.contract_months || e.duration_months} months. ${Math.round(e.onsite_ratio * 100)}% onsite.`}
              action={<Link to={`/app/deals/${deal.id}/estimation`} className="text-[13px] font-semibold text-brand-700 hover:underline whitespace-nowrap">Open team</Link>}>
              <TeamBars team={e.team} />
              {e.unfilled_roles > 0 && <p className="text-[12.5px] text-fit-gap-ink mt-3">{e.unfilled_roles} roles still need someone.</p>}
            </Panel>
          )}
        </div>
      </div>

      {p && (
        <Panel title="Price" sub={`Four ways to price this deal, shown against your cost and your ${p.min_margin}% margin floor. ${p.selected || "Target"} goes into the proposal.`}
          action={<Link to={`/app/deals/${deal.id}/pricing`} className="text-[13px] font-semibold text-brand-700 hover:underline whitespace-nowrap">Open pricing</Link>}>
          <div className="grid lg:grid-cols-[minmax(0,1fr)_280px] gap-x-10 gap-y-5 items-center">
            <PriceLadder cost={p.total_cost} floorMargin={p.min_margin} scenarios={p.scenarios} selected={p.selected || "Target"} list={p.list_price} fmt={fmt}
              onPick={() => nav(`/app/deals/${deal.id}/pricing`)} />
            <dl className="grid grid-cols-3 lg:grid-cols-1 gap-4 lg:border-l lg:border-line-soft lg:pl-8">
              <div><dt className="text-[12px] text-ink-muted">Proposed price</dt><dd className="font-display num text-[20px] sm:text-[24px] leading-tight text-brand-950">{fmt(deal.value / fx)}</dd></div>
              <div><dt className="text-[12px] text-ink-muted">Margin</dt><dd className="font-display num text-[20px] sm:text-[24px] leading-tight text-brand-950">{deal.margin_pct}%</dd></div>
              <div><dt className="text-[12px] text-ink-muted">Total cost</dt><dd className="font-display num text-[20px] sm:text-[24px] leading-tight text-brand-950">{fmt(p.total_cost)}</dd></div>
            </dl>
          </div>
        </Panel>
      )}

      <SimilarDeals deal={deal} />
      <NextStep deal={deal} />
    </div>
  );
}

const APPROVER_ROLE: Record<string, string> = {
  requirements: "pre-sales", matching: "pre-sales", gaps: "pre-sales", architecture: "the solution architect",
  estimation: "the solution architect", pricing: "finance", proposal: "pre-sales", handoff: "delivery",
};
const STAGE_LABEL: Record<string, string> = {
  requirements: "requirements", matching: "the capability match", gaps: "gaps and risks", architecture: "the architecture",
  estimation: "effort and team", pricing: "pricing", proposal: "the proposal", handoff: "the delivery handoff",
};

function NextStep({ deal }: { deal: any }) {
  const next = deal.stages?.find((s: any) => s.status === "draft");
  const approved = deal.stages?.filter((s: any) => s.status === "approved").length || 0;
  if (!next) return approved === 8 ? (
    <div className="card p-5 flex items-center gap-4"><div className="flex-1 text-[14px]">Every stage is approved. Download the proposal and the handoff pack from the menu at the top.</div></div>
  ) : null;
  return (
    <div className="rounded-lg bg-brand-950 text-white p-5 md:p-6 flex flex-wrap items-center gap-4">
      <div className="flex-1 min-w-[240px]">
        <div className="text-[13px] text-brand-200">{approved} of 8 stages approved</div>
        <div className="font-display text-[22px] mt-0.5">Next, {APPROVER_ROLE[next.stage]} reviews {STAGE_LABEL[next.stage]}.</div>
      </div>
      <Link to={`/app/deals/${deal.id}/${next.stage}`} className="btn bg-white text-brand-950 hover:bg-brand-50 h-10 px-5">Review {STAGE_LABEL[next.stage]} <ArrowRight className="h-4 w-4" /></Link>
    </div>
  );
}

/** "You've bid this before": the company's past deals most like this one, and how they went. Hidden when there are none. */
function SimilarDeals({ deal }: { deal: any }) {
  const { data } = useQuery({ queryKey: ["similar", deal.id], queryFn: () => api.get<any[]>(`/deals/${deal.id}/similar`), staleTime: 60_000 });
  if (!data?.length) return null;
  return (
    <section className="card p-5 md:p-6">
      <div className="flex items-start gap-3 mb-4">
        <span className="h-9 w-9 shrink-0 rounded-xl bg-gradient-to-b from-brand-50 to-white border border-brand-100 text-brand-600 grid place-items-center"><History className="h-[18px] w-[18px]" /></span>
        <div className="min-w-0">
          <h3 className="font-bold text-[15.5px] text-ink">You've bid this before</h3>
          <p className="text-[12.5px] text-ink-muted mt-0.5">Your past deals most like this one, by technologies, capabilities, industry and engagement type. Learn from how they went.</p>
        </div>
      </div>
      <div className="grid md:grid-cols-3 gap-3">
        {data.map((s) => (
          <Link key={s.id} to={`/app/deals/${s.id}`} className="group rounded-xl border border-line-soft bg-[#FBFCFD] p-4 transition-all duration-300 hover:border-brand-200 hover:bg-white hover:shadow-hover">
            <div className="flex items-center gap-2">
              <span className="num text-[12px] font-bold text-brand-700">{s.similarity}% alike</span>
              <span className="ml-auto"><DealStatus s={s.status} /></span>
            </div>
            <div className="mt-2 font-semibold text-[14px] leading-snug text-ink line-clamp-2 group-hover:text-brand-800">{s.name}</div>
            <div className="text-[12px] text-ink-muted mt-0.5 truncate">
              {s.client}{s.industry ? ` · ${s.industry}` : ""}{s.engagement_type ? ` · ${(ENGAGEMENT[s.engagement_type] || "").toLowerCase()}` : ""}
            </div>
            <dl className="mt-3 grid grid-cols-3 gap-2 text-[12px]">
              <div><dt className="text-ink-faint">Price</dt><dd className="num font-semibold text-ink">{s.value ? money(s.value, s.value_currency || "USD") : "—"}</dd></div>
              <div><dt className="text-ink-faint">Margin</dt><dd className="num font-semibold text-ink">{s.margin_pct != null ? `${s.margin_pct}%` : "—"}</dd></div>
              <div><dt className="text-ink-faint">Readiness</dt><dd className="num font-semibold text-ink">{s.readiness != null ? `${s.readiness}%` : "—"}</dd></div>
            </dl>
            {s.common_technologies?.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1">
                {s.common_technologies.slice(0, 5).map((t: string) => <span key={t} className="chip bg-white border border-line text-ink-soft font-medium">{t}</span>)}
              </div>
            )}
            {s.outcome_notes && <p className="mt-3 text-[12px] text-ink-soft italic line-clamp-2">“{s.outcome_notes}”</p>}
          </Link>
        ))}
      </div>
    </section>
  );
}
