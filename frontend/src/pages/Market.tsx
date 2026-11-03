import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Compass, Info, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Empty, PageLoader, StatStrip } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";

function shade(n: number, max: number) {
  if (!n) return "bg-white text-ink-faint";
  const r = n / Math.max(1, max);
  return r > 0.66 ? "bg-brand-700 text-white" : r > 0.33 ? "bg-brand-400 text-white" : r > 0.1 ? "bg-brand-200 text-brand-950" : "bg-brand-50 text-brand-900";
}

function MiniBars({ rows, unit = "" }: { rows: [string, number][]; unit?: string }) {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return (
    <ul className="space-y-1.5">
      {rows.map(([label, n]) => (
        <li key={label} className="grid grid-cols-[minmax(0,1fr)_120px_32px] items-center gap-2 text-[12.5px]">
          <span className="truncate" title={label}>{label}</span>
          <span className="h-2 rounded-full bg-line-soft overflow-hidden"><span className="block h-full rounded-full bg-brand-500" style={{ width: `${(n / max) * 100}%` }} /></span>
          <span className="num text-right text-ink-soft">{n}{unit}</span>
        </li>
      ))}
    </ul>
  );
}

export default function Market() {
  const { data, isLoading } = useQuery({ queryKey: ["market"], queryFn: () => api.get<any>("/insights/market") });
  const [sel, setSel] = useState<string | null>(null);
  if (isLoading || !data) return <PageLoader label="Counting demand for your offerings in public tenders" />;
  const offerings = data.offerings || [];
  const withDemand = offerings.filter((o: any) => o.total);
  const current = withDemand.find((o: any) => o.id === sel) || withDemand[0];
  const regions = (data.region_totals || []).map((r: any) => r[0]);
  const maxCell = Math.max(1, ...(data.matrix || []).flatMap((m: any) => Object.values(m.cells) as number[]));
  const maxWeek = Math.max(1, ...(data.weeks || []).map((w: any) => w.tenders));
  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1400px] space-y-5">
      <div className="stagger">
        <div className="eyebrow mb-1.5">Market insights</div>
        <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Where your offerings are in demand</h1>
        <p className="text-ink-muted text-[14px] mt-1">Counted from the {data.tenders_read.toLocaleString()} public tenders the radar read in the last {data.window_days} days, matched to your own capabilities and products.</p>
      </div>
      <div className="card px-5 py-3 text-[12.5px] text-ink-soft flex gap-2">
        <Info className="h-4 w-4 shrink-0 text-brand-600 mt-0.5" />
        <span>Each tender counts once, for your closest capability or product, and only when the notice clearly describes that kind of work. No AI and no outside market data: just the notices. Sources: {data.sources.join(", ")}.
          Not covered: {data.not_covered.map((n: any) => n.where).join("; ")}. To add a product, put it in your Knowledge library under Accelerators.</span>
      </div>
      {!withDemand.length ? (
        <div className="card"><Empty icon={<Compass className="h-8 w-8" />} title={data.tenders_read ? "No tenders matched your offerings yet" : "No tenders read yet"}>
          {data.tenders_read ? "None of the notices read so far clearly describes the work in your library. Check back after the next refresh, or add more capabilities and products." : "Market insights use the tenders the Opportunity radar reads. They appear after the first refresh."}
        </Empty></div>
      ) : (
        <>
          <StatStrip items={[
            { label: "Tenders matching your offerings", value: data.totals.matched, sub: `${data.totals.open} still open` },
            { label: "Offerings in demand", value: `${withDemand.length} of ${data.totals.offerings}`, sub: "Capabilities and products" },
            { label: "Countries", value: data.totals.countries, sub: "With at least one matching tender" },
            { label: "Biggest region", value: data.totals.top_region || "—", sub: "By matching tenders", tone: "brand" },
          ]} />
          <section className="card overflow-x-auto">
            <div className="px-5 py-4 border-b border-line"><div className="font-bold">Demand by region</div><div className="text-[12.5px] text-ink-muted">Matching tenders per offering and region. Select an offering for the detail.</div></div>
            <table className="w-full min-w-[760px] text-[12.5px]">
              <thead><tr><th className="th">Offering</th>{regions.map((r: string) => <th key={r} className="th text-center !normal-case !tracking-normal">{r}</th>)}<th className="th text-right">Total</th></tr></thead>
              <tbody>
                {data.matrix.map((m: any) => (
                  <tr key={m.id} onClick={() => setSel(m.id)} className={clsx("cursor-pointer", current?.id === m.id ? "bg-brand-50/60" : "hover:bg-paper")}>
                    <td className="td font-medium">{m.offering}</td>
                    {regions.map((r: string) => <td key={r} className="px-1 py-1"><div className={clsx("num rounded-md h-8 grid place-items-center font-semibold", shade(m.cells[r] || 0, maxCell))}>{m.cells[r] || ""}</div></td>)}
                    <td className="td text-right num font-semibold">{Object.values(m.cells).reduce((a: number, b: any) => a + b, 0) as number}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          {current && (
            <section className="card p-5">
              <div className="flex flex-wrap items-baseline gap-2 mb-4">
                <div className="font-bold text-[16px]">{current.name}</div>
                <span className="text-[12px] text-ink-muted">{current.kind} · {current.total} matching tenders, {current.open} still open</span>
                {Object.keys(current.value_by_currency).length > 0 && <span className="text-[12px] text-ink-muted">· stated value {Object.entries(current.value_by_currency).map(([c, v]) => money(v as number, c)).join(" + ")}</span>}
              </div>
              <div className="grid lg:grid-cols-3 gap-6">
                <div><div className="text-[12px] font-semibold text-ink-muted mb-2">Countries</div><MiniBars rows={current.countries} /></div>
                <div><div className="text-[12px] font-semibold text-ink-muted mb-2">Buyer sectors</div><MiniBars rows={current.sectors} />
                  <div className="text-[11.5px] text-ink-faint mt-2">Read from the buyer's name and the notice text.</div></div>
                <div><div className="text-[12px] font-semibold text-ink-muted mb-2">Buyers with most tenders</div>
                  <ul className="space-y-1 text-[12.5px]">{current.buyers.map(([b, n]: [string, number]) => <li key={b} className="flex gap-2"><span className="flex-1 truncate" title={b}>{b}</span><span className="num text-ink-soft">{n}</span></li>)}</ul></div>
              </div>
              {current.examples.length > 0 && (
                <div className="mt-5 pt-4 border-t border-line-soft">
                  <div className="text-[12px] font-semibold text-ink-muted mb-2">Closest open tenders</div>
                  <ul className="space-y-1.5 text-[13px]">{current.examples.map((e: any) => (
                    <li key={e.id} className="flex flex-wrap gap-x-3"><Link to={`/app/opportunities?t=${e.id}`} className="font-medium hover:text-brand-700">{e.title}</Link>
                      <span className="text-ink-muted text-[12px]">{e.country}{e.deadline ? ` · closes ${new Date(e.deadline).toLocaleDateString(undefined, { day: "numeric", month: "short" })}` : ""}{e.value ? ` · ${money(e.value, e.currency)}` : ""}</span></li>))}</ul>
                </div>
              )}
            </section>
          )}
          <div className="grid lg:grid-cols-2 gap-5">
            <section className="card p-5">
              <div className="font-bold flex items-center gap-2"><Compass className="h-4 w-4 text-ember-600" /> Where else you could sell</div>
              <div className="text-[12.5px] text-ink-muted mb-3">Regions with demand for an offering where you have no case study yet, or that you don't list in your supplier-network profile.</div>
              {data.untapped.length ? (
                <ul className="divide-y divide-line-soft text-[13px]">{data.untapped.map((u: any) => (
                  <li key={u.offering + u.region} className="py-2"><span className="font-semibold">{u.offering}</span> in <span className="font-semibold">{u.region}</span>: <span className="num">{u.tenders}</span> tenders.
                    <div className="text-[12px] text-ink-muted">{u.why}</div></li>))}</ul>
              ) : <div className="text-[13px] text-ink-muted">None yet: demand matches the regions where you already work.</div>}
            </section>
            <section className="card p-5">
              <div className="font-bold flex items-center gap-2"><TrendingUp className="h-4 w-4 text-brand-600" /> Matching tenders per week</div>
              <div className="text-[12.5px] text-ink-muted mb-4">By publication date. The history grows with every radar refresh.</div>
              {data.weeks.length ? (
                <div className="flex items-end gap-1.5 h-36" role="img" aria-label="Matching tenders per week">
                  {data.weeks.map((w: any) => (
                    <div key={w.week} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                      <span className="num text-[11px] text-ink-soft">{w.tenders}</span>
                      <div className="w-full rounded-t bg-brand-500" style={{ height: `${(w.tenders / maxWeek) * 100}px` }} />
                      <span className="text-[10.5px] text-ink-faint whitespace-nowrap">{new Date(w.week).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
                    </div>
                  ))}
                </div>
              ) : <div className="text-[13px] text-ink-muted">Not enough history yet.</div>}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
