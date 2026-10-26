import { useQuery } from "@tanstack/react-query";
import { Trophy } from "lucide-react";
import { Link } from "react-router-dom";
import { Empty, PageLoader, StatStrip } from "../components/ui";
import { api } from "../lib/api";
import { ENGAGEMENT, money } from "../lib/format";
import { DealStatus } from "./Dashboard";

type Row = { label: string; won: number; lost: number; win_rate: number | null; won_value: number };

/** One breakdown: a won/lost bar per group with its win rate. */
function Breakdown({ title, sub, rows, fmt = (s: string) => s }: { title: string; sub: string; rows: Row[]; fmt?: (s: string) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.won + r.lost));
  return (
    <section className="card card-hover p-5">
      <h2 className="font-bold text-[15px]">{title}</h2>
      <p className="text-[12.5px] text-ink-muted mt-0.5 mb-4">{sub}</p>
      {rows.length === 0 ? <div className="text-[13px] text-ink-muted">Not enough decided deals yet.</div> : (
        <ul className="space-y-3">
          {rows.map((r) => (
            <li key={r.label}>
              <div className="flex items-baseline justify-between gap-3 text-[13px]">
                <span className="text-ink truncate">{fmt(r.label)}</span>
                <span className="num whitespace-nowrap"><span className="font-semibold text-ink">{r.win_rate ?? "—"}%</span> <span className="text-ink-muted">won · {r.won} of {r.won + r.lost}</span></span>
              </div>
              <div className="mt-1.5 flex h-2 gap-[2px]" style={{ width: `${((r.won + r.lost) / max) * 100}%` }}
                role="img" aria-label={`${fmt(r.label)}: ${r.won} won, ${r.lost} lost`}>
                {r.won > 0 && <div className="h-full rounded-l-full last:rounded-r-full bg-ok" style={{ flex: r.won }} />}
                {r.lost > 0 && <div className="h-full first:rounded-l-full rounded-r-full bg-fit-gap/80" style={{ flex: r.lost }} />}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Compare({ label, won, lost, suffix = "%", fmt }: { label: string; won: number | null; lost: number | null; suffix?: string; fmt?: (v: number) => string }) {
  const show = (v: number | null) => (v == null ? "—" : fmt ? fmt(v) : `${v}${suffix}`);
  const max = Math.max(1, won || 0, lost || 0);
  return (
    <div>
      <div className="text-[12.5px] text-ink-muted mb-2">{label}</div>
      {[["Won", won, "bg-ok"], ["Lost", lost, "bg-fit-gap/80"]].map(([k, v, c]) => (
        <div key={k as string} className="flex items-center gap-2 text-[12.5px] mb-1.5">
          <span className="w-9 text-ink-soft">{k as string}</span>
          <div className="flex-1 h-2 rounded-full bg-line-soft overflow-hidden"><div className={`h-full rounded-full ${c}`} style={{ width: `${(((v as number) || 0) / max) * 100}%` }} /></div>
          <span className="num w-20 text-right font-semibold">{show(v as number | null)}</span>
        </div>
      ))}
    </div>
  );
}

export default function WinLoss() {
  const { data } = useQuery({ queryKey: ["winloss"], queryFn: () => api.get("/insights/winloss") });
  if (!data) return <PageLoader />;
  const t = data.totals;
  const ccy = data.currency;
  const wl = data.won_vs_lost;
  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1400px]">
      <div className="stagger mb-6">
        <div className="eyebrow mb-1.5">Outcomes</div>
        <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Win/loss insights</h1>
        <p className="text-ink-muted text-[14px] mt-1">What your won and lost deals have in common, so the next bid is priced and pitched better.</p>
      </div>
      {t.decided === 0 ? (
        <div className="card">
          <Empty icon={<Trophy className="h-8 w-8" />} title="No decided deals yet" action={<Link to="/app/deals" className="btn-primary">Go to deals</Link>}>
            When a deal is decided, open it and choose Won or Lost from the Outcome menu. Insights appear here from the first decision.
          </Empty>
        </div>
      ) : (
        <>
          <div className="rise-3d">
            <StatStrip items={[
              { label: "Win rate", value: t.win_rate != null ? `${t.win_rate}%` : "—", sub: `${t.won} won, ${t.lost} lost` },
              { label: "Value won", value: money(t.won_value, ccy), sub: "At the proposed price" },
              { label: "Still open", value: t.open, sub: "In review or submitted" },
              { label: "No bid", value: t.no_bid, sub: "Deals you chose not to bid" },
            ]} />
          </div>
          <section className="card p-5 mt-5">
            <h2 className="font-bold text-[15px]">Won compared with lost</h2>
            <p className="text-[12.5px] text-ink-muted mt-0.5 mb-5">Averages across decided deals.</p>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-x-8 gap-y-5">
              <Compare label="Bid readiness with the plan" won={wl.readiness[0]} lost={wl.readiness[1]} />
              <Compare label="Margin" won={wl.margin[0]} lost={wl.margin[1]} />
              <Compare label="Coverage of requirements" won={wl.coverage[0]} lost={wl.coverage[1]} />
              <Compare label="Deal size" won={wl.value[0]} lost={wl.value[1]} fmt={(v) => money(v, ccy)} />
            </div>
          </section>
          <div className="grid lg:grid-cols-2 gap-5 mt-5 stagger">
            <Breakdown title="By margin" sub="Where your price wins: compare win rates across margin bands." rows={data.by_margin} />
            <Breakdown title="By deal size" sub="Proposed price, in your company currency." rows={data.by_size} />
            <Breakdown title="By industry" sub="Industries where your offer lands, and where it doesn't." rows={data.by_industry} />
            <Breakdown title="By engagement type" sub="Implementation, managed services, consulting or product." rows={data.by_engagement}
              fmt={(s) => (s === "not_set" ? "Not set" : ENGAGEMENT[s] || s)} />
          </div>
          <section className="card mt-5 overflow-hidden">
            <div className="px-5 py-4 border-b border-line"><h2 className="font-bold text-[15px]">Recent decisions</h2></div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px]">
                <thead><tr><th className="th">Deal</th><th className="th">Outcome</th><th className="th text-right">Price</th><th className="th text-right">Margin</th><th className="th text-right">Readiness</th><th className="th">Notes</th></tr></thead>
                <tbody>
                  {data.recent.map((r: any) => (
                    <tr key={r.id} className="hover:bg-brand-50/40">
                      <td className="td"><Link to={`/app/deals/${r.id}`} className="font-semibold hover:text-brand-700">{r.name}</Link><div className="text-[12px] text-ink-muted">{r.client} · {r.industry}</div></td>
                      <td className="td"><DealStatus s={r.status} /></td>
                      <td className="td text-right num">{r.value ? money(r.value, ccy) : "—"}</td>
                      <td className="td text-right num">{r.margin_pct != null ? `${r.margin_pct}%` : "—"}</td>
                      <td className="td text-right num">{r.readiness != null ? `${r.readiness}%` : "—"}</td>
                      <td className="td text-[12.5px] text-ink-soft max-w-[320px]">{r.notes || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
