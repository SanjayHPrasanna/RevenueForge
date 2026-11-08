import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, ExternalLink, Info, Search, Users } from "lucide-react";
import { useState } from "react";
import { Empty, Spinner, StatStrip, useToast } from "../components/ui";
import { api, getToken } from "../lib/api";
import { money } from "../lib/format";

const BAND_STYLE: Record<string, string> = {
  "Strong match": "bg-[#E4F1F7] text-fit-strong-ink", "Possible match": "bg-[#FBF1DD] text-fit-partial-ink", "Weak match": "bg-line-soft text-ink-muted",
};
const REGIONS = ["Europe", "United Kingdom", "North America", "Latin America & Caribbean", "Middle East & North Africa", "Sub-Saharan Africa", "South Asia", "East Asia & Pacific", "Central Asia & Caucasus", "Other"];
type Tab = "buying" | "before" | "renewals" | "customers";

function day(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "Not stated";
}

function Score({ it }: { it: any }) {
  return (
    <div className="flex items-center gap-2">
      <span className="num font-bold text-[15px] w-8 text-right">{it.score}</span>
      <span className={clsx("chip whitespace-nowrap", BAND_STYLE[it.band] || BAND_STYLE["Weak match"])}>{it.band}</span>
    </div>
  );
}

function Notice({ it }: { it: any }) {
  return (
    <div className="min-w-0">
      {it.url ? (
        <a href={it.url} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-brand-700 inline-flex gap-1 items-start">
          <span>{it.title}</span><ExternalLink className="h-3 w-3 mt-1 shrink-0 text-ink-faint" />
        </a>
      ) : <span className="font-medium">{it.title}</span>}
      <div className="text-[12px] text-ink-muted">{it.buyer || "Buyer not stated"}{it.country ? ` · ${it.country}` : ""} · {it.source_name}</div>
      {it.why?.length > 0 && <div className="text-[12px] text-ink-soft mt-0.5">Shared with your product: {it.why.join(", ")}</div>}
      {it.notes?.map((n: string) => <div key={n} className="text-[11.5px] text-ember-700 mt-0.5">{n}</div>)}
    </div>
  );
}

async function exportXlsx(body: any) {
  const token = getToken();
  const res = await fetch("/api/insights/customers/export", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = "Download failed";
    try { msg = (await res.json()).detail || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  const cd = res.headers.get("content-disposition") || "";
  const star = cd.match(/filename\*=utf-8''([^;]+)/i);
  const plain = cd.match(/filename="([^"]+)"/);
  const name = star ? decodeURIComponent(star[1]) : plain ? plain[1] : "Customers.xlsx";
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export default function Customers() {
  const toast = useToast();
  const caps = useQuery({ queryKey: ["lib", "capabilities"], queryFn: () => api.get<any[]>("/library/capabilities") });
  const accs = useQuery({ queryKey: ["lib", "accelerators"], queryFn: () => api.get<any[]>("/library/accelerators") });
  const [mode, setMode] = useState<"library" | "describe">("library");
  const [itemId, setItemId] = useState("");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [regions, setRegions] = useState<string[]>([]);
  const [tab, setTab] = useState<Tab>("buying");
  const [exporting, setExporting] = useState(false);
  const [lastBody, setLastBody] = useState<any>(null);

  const run = useMutation({
    mutationFn: (body: any) => api.post<any>("/insights/customers", body),
    onSuccess: (_d, body) => { setLastBody(body); setTab("buying"); },
    onError: (e: any) => toast("error", e.message),
  });
  const body = mode === "library" ? { item_id: itemId, regions } : { name: name.trim(), description: desc.trim(), regions };
  const ready = mode === "library" ? !!itemId : desc.trim().length >= 20;
  const r = run.data;
  const items: any[] = (caps.data || []).map((c) => ({ ...c, group: "Capabilities" })).concat((accs.data || []).map((a) => ({ ...a, group: "Products (accelerators)" })));

  const tabs: { key: Tab; label: string; n: number }[] = r ? [
    { key: "buying", label: "Buying now", n: r.buying_now.length },
    { key: "before", label: "Bought before", n: r.bought_before.length },
    { key: "renewals", label: "Renewals coming up", n: r.renewals.length },
    { key: "customers", label: "Customers", n: r.customers.length },
  ] : [];

  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1400px] space-y-5">
      <div className="stagger">
        <div className="eyebrow mb-1.5">Find customers</div>
        <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Who could buy this product</h1>
        <p className="text-ink-muted text-[14px] mt-1">Pick a product from your library, or describe one you have built or plan to build. You'll see open tenders it could answer, who bought this kind of work before and from whom, and contracts ending in the next 6 to 18 months.</p>
      </div>

      <section className="card p-5 space-y-4">
        <div className="flex gap-2" role="tablist">
          <button role="tab" aria-selected={mode === "library"} className={mode === "library" ? "btn-primary" : "btn-outline"} onClick={() => setMode("library")}>From my library</button>
          <button role="tab" aria-selected={mode === "describe"} className={mode === "describe" ? "btn-primary" : "btn-outline"} onClick={() => setMode("describe")}>Describe a product</button>
        </div>
        {mode === "library" ? (
          <label className="block max-w-xl">
            <span className="text-[12.5px] font-semibold text-ink-muted">Product or capability</span>
            <select className="input mt-1 w-full" value={itemId} onChange={(e) => setItemId(e.target.value)}>
              <option value="">{caps.isLoading || accs.isLoading ? "Loading your library…" : items.length ? "Choose one" : "Your library is empty"}</option>
              {["Products (accelerators)", "Capabilities"].map((g) => {
                const opts = items.filter((i) => i.group === g);
                return opts.length ? <optgroup key={g} label={g}>{opts.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</optgroup> : null;
              })}
            </select>
          </label>
        ) : (
          <div className="grid gap-3 max-w-3xl">
            <label className="block"><span className="text-[12.5px] font-semibold text-ink-muted">Name (optional)</span>
              <input className="input mt-1 w-full" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Clinic integration hub" /></label>
            <label className="block"><span className="text-[12.5px] font-semibold text-ink-muted">What it does, in plain words</span>
              <textarea className="input mt-1 w-full min-h-[96px]" maxLength={4000} value={desc} onChange={(e) => setDesc(e.target.value)}
                placeholder="e.g. Connects hospital laboratory and radiology systems using HL7 and FHIR interfaces, with monitoring and alerting for failed messages." />
              <span className="text-[11.5px] text-ink-faint">Describe the work, who uses it and the main technologies. A list of keywords matches poorly. At least 20 characters.</span></label>
          </div>
        )}
        <div>
          <div className="text-[12.5px] font-semibold text-ink-muted mb-1.5">Regions (none selected means all)</div>
          <div className="flex flex-wrap gap-1.5">
            {(r?.regions_available || REGIONS).map((g: string) => (
              <button key={g} aria-pressed={regions.includes(g)} onClick={() => setRegions((x) => x.includes(g) ? x.filter((y) => y !== g) : [...x, g])}
                className={clsx("chip border", regions.includes(g) ? "bg-brand-700 text-white border-brand-700" : "bg-white border-line text-ink-soft hover:border-brand-400")}>{g}</button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <button className="btn-primary" disabled={!ready || run.isPending} onClick={() => run.mutate(body)}>
            {run.isPending ? <Spinner /> : <Search className="h-4 w-4" />} Find customers
          </button>
          {r && lastBody && (
            <button className="btn-outline" disabled={exporting} onClick={() => { setExporting(true); exportXlsx(lastBody).catch((e) => toast("error", e.message)).finally(() => setExporting(false)); }}>
              {exporting ? <Spinner /> : <Download className="h-4 w-4" />} Download Excel
            </button>
          )}
        </div>
      </section>

      {r && (
        <>
          {r.warning && <div className="card px-5 py-3 text-[13px] text-ember-700 border-ember-300 bg-ember-50/40">{r.warning}</div>}
          <div className="card px-5 py-3 text-[12.5px] text-ink-soft flex gap-2">
            <Info className="h-4 w-4 shrink-0 text-brand-600 mt-0.5" />
            <span>
              Matched {r.product.source === "description" && r.product.name === "Described product" ? "your description" : <b>{r.product.name}</b>} on: {r.key_terms.length ? r.key_terms.join(", ") : "nothing specific"}. A notice is listed only when it shares at least two of these, and is a strong match only when it covers at least half of what the notice asks for. No AI is used.
              {r.hidden_weak > 0 && ` ${r.hidden_weak.toLocaleString()} weaker ${r.hidden_weak === 1 ? "notice was" : "notices were"} left out.`}
            </span>
          </div>
          <StatStrip items={[
            { label: "Buying now", value: r.buying_now.length, sub: "Open tenders" },
            { label: "Bought before", value: r.bought_before.length, sub: "Past contract awards" },
            { label: "Renewals coming up", value: r.renewals.length, sub: `Ending ${day(r.renewal_window?.from)} to ${day(r.renewal_window?.to)}`, tone: "brand" },
            { label: "Customers", value: r.customers.length, sub: "Distinct public buyers" },
          ]} />

          <section className="card">
            <div className="flex flex-wrap gap-1 px-3 pt-3 border-b border-line" role="tablist">
              {tabs.map((t) => (
                <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
                  className={clsx("px-3 py-2 text-[13px] font-semibold border-b-2 -mb-px", tab === t.key ? "border-brand-700 text-brand-900" : "border-transparent text-ink-muted hover:text-ink")}>
                  {t.label} <span className="num text-ink-faint">{t.n}</span>
                </button>
              ))}
            </div>
            <div className="overflow-x-auto">
              {tab === "buying" && (r.buying_now.length ? (
                <table className="w-full min-w-[820px] text-[13px]">
                  <thead><tr><th className="th">Fit</th><th className="th">Tender</th><th className="th">Closes</th><th className="th text-right">Stated value</th></tr></thead>
                  <tbody>{r.buying_now.map((it: any) => (
                    <tr key={it.id} className="border-t border-line-soft"><td className="td align-top"><Score it={it} /></td><td className="td align-top"><Notice it={it} /></td>
                      <td className="td align-top whitespace-nowrap">{day(it.deadline)}</td><td className="td align-top text-right num">{it.value ? money(it.value, it.currency || "EUR") : "—"}</td></tr>))}</tbody>
                </table>
              ) : <Empty icon={<Search className="h-8 w-8" />} title="No open tenders clearly match">None of the open notices read so far describes this kind of work closely enough. Check after the next refresh.</Empty>)}

              {(tab === "before" || tab === "renewals") && (() => {
                const rows = tab === "before" ? r.bought_before : r.renewals;
                if (!rows.length) return (
                  <Empty icon={<Search className="h-8 w-8" />} title={tab === "before" ? "No past awards clearly match" : "No matching contracts end in this window"}>
                    {tab === "renewals"
                      ? `${r.renewal_window?.ending_sooner || 0} matching contracts end sooner than 6 months; ${r.renewal_window?.no_end_date || 0} have no end date in the notice.`
                      : "Award history builds up a month further back with each refresh, up to a year."}
                  </Empty>);
                return (
                  <>
                    {tab === "renewals" && <div className="px-5 py-2 text-[12px] text-ink-muted">Ending dates come from the award notice: stated, or worked out from the start date and duration. Contracts can be extended, so check before you plan around them. {r.renewal_window?.no_end_date || 0} matching awards had no end date and are not shown here.</div>}
                    <table className="w-full min-w-[900px] text-[13px]">
                      <thead><tr><th className="th">Fit</th><th className="th">Contract</th><th className="th">Won by</th><th className="th">Awarded</th><th className="th">Ends</th><th className="th text-right">Value</th></tr></thead>
                      <tbody>{rows.map((it: any) => (
                        <tr key={it.id} className="border-t border-line-soft"><td className="td align-top"><Score it={it} /></td><td className="td align-top"><Notice it={it} /></td>
                          <td className="td align-top text-[12.5px]">{it.suppliers?.length ? it.suppliers.join("; ") : "Not stated"}</td>
                          <td className="td align-top whitespace-nowrap">{day(it.awarded)}</td>
                          <td className="td align-top whitespace-nowrap">{day(it.contract_end)}{it.end_basis === "start + duration" && <span className="block text-[11px] text-ink-faint">From duration</span>}</td>
                          <td className="td align-top text-right num">{it.value ? money(it.value, it.currency || "EUR") : "—"}</td></tr>))}</tbody>
                    </table>
                  </>
                );
              })()}

              {tab === "customers" && (r.customers.length ? (
                <table className="w-full min-w-[900px] text-[13px]">
                  <thead><tr><th className="th">Buyer</th><th className="th text-right">Open tenders</th><th className="th text-right">Past awards</th><th className="th">Spent (stated)</th><th className="th">Bought from</th><th className="th">Next contract end</th></tr></thead>
                  <tbody>{r.customers.map((c: any) => (
                    <tr key={c.buyer} className="border-t border-line-soft">
                      <td className="td align-top"><div className="font-medium">{c.buyer}</div><div className="text-[12px] text-ink-muted">{[c.country, c.region !== c.country ? c.region : ""].filter(Boolean).join(" · ")} · best fit {c.best_score}</div></td>
                      <td className="td align-top text-right num">{c.open_tenders}</td><td className="td align-top text-right num">{c.past_awards}</td>
                      <td className="td align-top num">{Object.keys(c.value).length ? Object.entries(c.value).map(([k, v]) => money(v as number, k)).join(" + ") : "—"}</td>
                      <td className="td align-top text-[12.5px]">{c.suppliers.length ? c.suppliers.join("; ") : "—"}</td>
                      <td className="td align-top whitespace-nowrap">{c.next_renewal ? day(c.next_renewal) : "—"}</td>
                    </tr>))}</tbody>
                </table>
              ) : <Empty icon={<Users className="h-8 w-8" />} title="No buyers yet">Buyers appear once a tender or award matches.</Empty>)}
            </div>
          </section>

          <div className="card px-5 py-4 text-[12.5px] text-ink-soft space-y-1">
            <div className="font-semibold text-ink">What this covers</div>
            <div>Open tenders from: {r.coverage.tender_sources.join(", ") || "none yet"}.</div>
            <div>Past awards: {r.coverage.award_sources.length ? r.coverage.award_sources.map((a: any) => `${a.source} (${a.stored.toLocaleString()}${a.since ? ` since ${day(a.since)}` : ""})`).join(", ") : "none stored yet. They are read with the next refresh."}.</div>
            <ul className="list-disc pl-5">{r.coverage.limits.map((l: string) => <li key={l}>{l}</li>)}</ul>
            {r.coverage.not_covered?.length > 0 && <div>Not covered: {r.coverage.not_covered.map((n: any) => n.where).join("; ")}.</div>}
            <div className="text-ink-faint">Notices are public-sector data used under each publisher's licence; follow each link for the original.</div>
          </div>
        </>
      )}
    </div>
  );
}
