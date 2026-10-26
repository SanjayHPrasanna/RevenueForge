import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Briefcase, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { Empty, Meter, PageLoader, Stat, StatStrip } from "../components/ui";
import { useTilt } from "../components/motion";
import { Bars, FitLegend, useTip } from "../components/viz";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ENGAGEMENT, FIT, money } from "../lib/format";

const MIX = FIT.map((f) => ({ key: f.key, label: f.label, fill: f.fill }));

export function MatchMixBar({ mix, height = 12 }: { mix: Record<string, number>; height?: number }) {
  const total = MIX.reduce((s, m) => s + (mix[m.key] || 0), 0);
  if (!total) return null;
  return (
    <div>
      <div className="flex w-full gap-[2px]" style={{ height }} role="img" aria-label={MIX.map((m) => `${m.label} ${mix[m.key] || 0}`).join(", ")}>
        {MIX.map((m) =>
          mix[m.key] ? (
            <div key={m.key} title={`${m.label}: ${mix[m.key]} (${Math.round((mix[m.key] / total) * 100)}%)`} className="first:rounded-l last:rounded-r h-full"
              style={{ width: `${(mix[m.key] / total) * 100}%`, background: m.key === "confirm" ? "white" : m.fill, boxShadow: m.key === "confirm" ? `inset 0 0 0 1.5px ${m.fill}` : undefined }} />
          ) : null,
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[12px] text-ink-soft">
        {MIX.map((m) => (
          <span key={m.key} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: m.key === "confirm" ? "white" : m.fill, boxShadow: m.key === "confirm" ? `inset 0 0 0 1.5px ${m.fill}` : undefined }} />
            {m.label} <span className="num font-semibold text-ink">{mix[m.key] || 0}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function HBars({ rows, max }: { rows: { label: string; value: number; sub?: string }[]; max?: number }) {
  const m = max || Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 items-center" title={`${r.label}: ${r.value}`}>
          <div className="min-w-0">
            <div className="text-[13px] text-ink truncate">{r.label}</div>
            <div className="h-1.5 mt-1 rounded-full bg-line-soft">
              <div className="h-full rounded-full bg-brand-500" style={{ width: `${(r.value / m) * 100}%` }} />
            </div>
          </div>
          <div className="num text-[13px] font-semibold text-ink-soft">{r.value}</div>
        </li>
      ))}
    </ul>
  );
}

const STATUS: Record<string, string> = {
  processing: "Processing", in_review: "In review", submitted: "Submitted", won: "Won", lost: "Lost", failed: "Failed", no_bid: "No bid", new: "New",
};
export function DealStatus({ s }: { s: string }) {
  const c: Record<string, string> = {
    processing: "bg-ember-50 text-ember-600", in_review: "bg-brand-50 text-brand-700", submitted: "bg-[#EEF0FB] text-[#4A54A8]",
    won: "bg-ok-bg text-ok", lost: "bg-[#FBE7E5] text-fit-gap-ink", failed: "bg-[#FBE7E5] text-fit-gap-ink", no_bid: "bg-line-soft text-ink-muted",
  };
  return <span className={clsx("chip", c[s] || "bg-line-soft text-ink-muted")}>{STATUS[s] || s}</span>;
}

export default function Dashboard() {
  const { user } = useAuth();
  const { show, hide } = useTip();
  const tilt = useTilt<HTMLDivElement>(1.6);
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get("/dashboard"), refetchInterval: 8000 });
  if (isLoading || !data) return <PageLoader />;
  const k = data.kpis;
  const ccy = k.currency;
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1400px]">
      <div className="flex flex-wrap items-end gap-3 mb-6">
        <div className="stagger">
          <div className="eyebrow mb-1.5">Pipeline overview</div>
          <h1 className="font-display text-[34px] md:text-[44px] leading-[1.05] tracking-[-0.02em] text-brand-950">{hello}, {user?.name.split(" ")[0]}</h1>
          <p className="text-ink-muted text-[14px] mt-1">Your bid pipeline, and what it says about your capabilities.</p>
        </div>
        <div className="flex-1" />
        <Link to="/app/deals?new=1" className="btn-primary h-10 px-4"><Plus className="h-4 w-4" /> New deal</Link>
      </div>

      <div className="rise-3d">
      <div ref={tilt} className="tilt tilt-glare rounded-xl2 hover:shadow-lift">

      <StatStrip items={[
        { label: "Pipeline value", value: money(k.pipeline_value, ccy), sub: `${money(k.weighted_pipeline, ccy)} weighted by bid readiness` },
        { label: "Active deals", value: k.active, sub: `${k.deals} in total, ${k.requirements.toLocaleString()} requirements analysed` },
        { label: "Average bid readiness", value: k.avg_readiness != null ? `${k.avg_readiness}%` : "—", sub: "With mitigation plans in place" },
        { label: "Classification accuracy", value: k.classification_accuracy != null ? `${k.classification_accuracy}%` : "—", sub: k.reviewed ? `Measured on ${k.reviewed} reviewed requirements` : "Review requirements in a deal to measure it" },
        { label: "Win rate", value: k.win_rate != null ? `${k.win_rate}%` : "—", sub: `${k.won} won, ${k.lost} lost` },
      ]} />
      </div>
      </div>

      <section className="card mt-5 min-w-0 overflow-hidden rise-3d" style={{ animationDelay: ".08s" }}>
        <div className="px-5 py-4 border-b border-line flex items-center gap-3">
          <div className="flex-1 min-w-0"><h2 className="font-bold text-[15.5px]">Deals</h2><p className="text-[12.5px] text-ink-muted">Each bar is a deal's requirements, coloured by how well you cover them.</p></div>
          <FitLegend className="hidden lg:flex" />
          <Link to="/app/deals" className="text-[13px] text-brand-700 font-semibold inline-flex items-center gap-1 whitespace-nowrap">All deals <ArrowRight className="h-3.5 w-3.5" /></Link>
        </div>
        {data.deals.length === 0 ? (
          <Empty icon={<Briefcase className="h-8 w-8" />} title="No deals yet" action={<Link to="/app/deals?new=1" className="btn-primary">Upload an RFP</Link>}>
            Upload an RFP, RFI or SOW and RevenueForge will build the full deal package.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px]">
              <thead>
                <tr><th className="th">Deal</th><th className="th">Status</th><th className="th w-[26%]">Coverage</th><th className="th">Bid readiness</th><th className="th text-right">Value</th><th className="th text-right">Margin</th></tr>
              </thead>
              <tbody>
                {data.deals.slice(0, 8).map((d: any) => {
                  const total = FIT.reduce((n, f) => n + (d.match_mix?.[f.key] || 0), 0);
                  return (
                    <tr key={d.id} className="hover:bg-brand-50/40">
                      <td className="td">
                        <Link to={`/app/deals/${d.id}`} className="font-semibold hover:text-brand-700 line-clamp-1">{d.name}</Link>
                        <div className="text-[12px] text-ink-muted">{d.client}{d.engagement_type ? `, ${(ENGAGEMENT[d.engagement_type] || "").toLowerCase()}` : ""}{d.due_date ? `. Due ${d.due_date}` : ""}</div>
                      </td>
                      <td className="td"><DealStatus s={d.status} /></td>
                      <td className="td">
                        {total ? (
                          <div className="flex gap-[2px] h-[10px] mt-1.5" role="img" aria-label={FIT.map((f) => `${f.label} ${d.match_mix?.[f.key] || 0}`).join(", ")}
                            onMouseMove={(e) => show(e, <div><b>{d.name}</b>{FIT.map((f) => <div key={f.key} className="num">{f.label}: {d.match_mix?.[f.key] || 0}</div>)}</div>)} onMouseLeave={hide}>
                            {FIT.map((f) => d.match_mix?.[f.key] ? (
                              <div key={f.key} className="h-full first:rounded-l last:rounded-r" style={{ flex: d.match_mix[f.key], background: "hollow" in f ? "white" : f.fill, boxShadow: "hollow" in f ? `inset 0 0 0 1.5px ${f.fill}` : undefined }} />
                            ) : null)}
                          </div>
                        ) : <span className="text-ink-faint text-[13px]">—</span>}
                      </td>
                      <td className="td w-[170px]">
                        {d.readiness != null ? (
                          <>
                            <div className="flex justify-between text-[12px]"><span className="text-ink-soft truncate pr-2">{d.verdict}</span><span className="num font-semibold">{d.readiness}%</span></div>
                            <Meter value={d.readiness} className="mt-1" />
                          </>
                        ) : <span className="text-ink-faint text-[13px]">—</span>}
                      </td>
                      <td className="td text-right num font-semibold whitespace-nowrap">{d.value ? money(d.value, d.value_currency || ccy) : "—"}</td>
                      <td className="td text-right num">{d.margin_pct != null ? `${d.margin_pct}%` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid lg:grid-cols-3 gap-5 mt-5 stagger">
        <section className="card card-hover p-5">
          <h2 className="font-bold text-[15px]">Skills the pipeline is asking for</h2>
          <p className="text-[12.5px] text-ink-muted mt-0.5 mb-4">Technologies in RFPs you can't cover today. A hiring and training signal.</p>
          {data.skill_gaps.length ? (
            <Bars rows={data.skill_gaps.map((g: any) => ({ label: g.technology, value: g.requirements }))} format={(v) => `${v}`} color="#CC3D3D" />
          ) : <div className="text-sm text-ink-muted">No gaps yet.</div>}
        </section>

        <section className="card card-hover p-5">
          <h2 className="font-bold text-[15px]">Most-matched capabilities</h2>
          <p className="text-[12.5px] text-ink-muted mt-0.5 mb-4">Where your offer is landing with clients.</p>
          {data.capability_demand.length ? <Bars rows={data.capability_demand.map((c: any) => ({ label: c.capability, value: c.requirements }))} format={(v) => `${v}`} /> : <div className="text-sm text-ink-muted">No matches yet.</div>}
        </section>

        <section className="card card-hover p-5">
          <h2 className="font-bold text-[15px]">Across all deals</h2>
          <p className="text-[12.5px] text-ink-muted mt-0.5 mb-4">How every requirement analysed so far is covered.</p>
          <MatchMixBar mix={data.match_mix} />
          <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-2 text-[13px]">
            {Object.entries(data.requirement_categories).map(([c, n]: any) => (
              <div key={c} className="flex justify-between border-b border-line-soft pb-1.5"><span className="text-ink-soft">{c}</span><span className="num font-semibold">{n}</span></div>
            ))}
          </div>
          <div className="mt-5 text-[13px] text-ink-soft">
            <span className="num font-semibold text-ink">{k.available_people}</span> of <span className="num font-semibold text-ink">{k.people}</span> people are at least half available for new work.
          </div>
        </section>
      </div>
    </div>
  );
}
