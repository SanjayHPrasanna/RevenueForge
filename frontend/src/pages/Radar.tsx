import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bookmark, ChevronDown, Mail, ExternalLink, EyeOff, Globe2, Info, RefreshCw, Radar as RadarIcon, Search, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Dropzone, Empty, Modal, PageLoader, Spinner, StatStrip, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ago, money } from "../lib/format";

type Item = {
  id: string; source: string; source_name: string; title: string; buyer: string; country: string; region: string; notice_type: string;
  value: number | null; currency: string; published: string | null; deadline: string | null; url: string; language: string;
  categories: { code: string; label: string }[]; score: number | null; band: string | null; status: string; deal_id: string;
  top_match: string; missing_standards: string[]; summary?: string;
};

const BAND_STYLE: Record<string, string> = {
  "Strong fit": "bg-[#E4F1F7] text-fit-strong-ink", "Possible fit": "bg-[#FBF1DD] text-fit-partial-ink", "Weak fit": "bg-line-soft text-ink-muted",
};

function daysLeft(iso: string | null) {
  if (!iso) return null;
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

function Due({ iso }: { iso: string | null }) {
  const d = daysLeft(iso);
  if (d == null) return <span className="text-ink-faint">Not stated</span>;
  return (
    <span className={clsx("num", d <= 7 ? "text-fit-gap-ink font-semibold" : d <= 14 ? "text-ember-600" : "text-ink-soft")}>
      {d <= 0 ? "Today" : `${d} day${d === 1 ? "" : "s"}`}
      <span className="block text-[11.5px] text-ink-faint font-normal">{new Date(iso!).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</span>
    </span>
  );
}

function Fit({ score, band }: { score: number | null; band: string | null }) {
  if (score == null) return <span className="text-ink-faint">—</span>;
  return (
    <div className="flex items-center gap-2">
      <span className="num font-bold text-[15px] w-8 text-right">{score}</span>
      <span className={clsx("chip whitespace-nowrap", BAND_STYLE[band || ""] || BAND_STYLE["Weak fit"])}>{band}</span>
    </div>
  );
}

function Sources() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({ queryKey: ["radar-sources"], queryFn: () => api.get<any>("/radar/sources"), refetchInterval: (q) => ((q.state.data as any)?.refresh?.running ? 5000 : false) });
  const refresh = useMutation({
    mutationFn: () => api.post<any>("/radar/refresh"),
    onSuccess: (r) => { toast("ok", r.message); qc.invalidateQueries({ queryKey: ["radar-sources"] }); },
    onError: (e: any) => toast("error", e.message),
  });
  useEffect(() => { if (data && !data.refresh?.running) qc.invalidateQueries({ queryKey: ["radar"] }); }, [data?.refresh?.running]);
  if (!data) return null;
  const live = data.sources.filter((s: any) => s.enabled);
  const last = live.map((s: any) => s.last_ok).filter(Boolean).sort().pop();
  return (
    <section className="card mb-4">
      <div className="flex flex-wrap items-center gap-3 px-5 py-3.5">
        <Globe2 className="h-5 w-5 text-brand-600" />
        <div className="flex-1 min-w-[260px] text-[13px]">
          <span className="font-semibold">{data.total.toLocaleString()} open tenders</span> from {live.map((s: any) => s.name).join(", ")}.
          <span className="text-ink-muted"> {last ? `Last read ${ago(last)}.` : "Not read yet."}{data.refresh?.running ? ` Reading ${data.refresh.current || "sources"} now…` : ""}</span>
        </div>
        <button className="btn-ghost h-8" onClick={() => setOpen(!open)} aria-expanded={open}>What's covered <ChevronDown className={clsx("h-4 w-4 transition-transform", open && "rotate-180")} /></button>
        {user?.role === "admin" && (
          <button className="btn-outline h-8" disabled={refresh.isPending || data.refresh?.running} onClick={() => refresh.mutate()}>
            {data.refresh?.running ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Refresh now
          </button>
        )}
      </div>
      {open && (
        <div className="border-t border-line-soft px-5 py-4 grid lg:grid-cols-2 gap-6 text-[13px] anim-fade-in">
          <div>
            <div className="font-semibold mb-2">Sources read</div>
            <ul className="space-y-2.5">
              {data.sources.map((s: any) => (
                <li key={s.key} className="flex gap-2">
                  <span className={clsx("mt-1.5 h-2 w-2 rounded-full shrink-0", !s.enabled ? "bg-line" : s.error ? "bg-fit-gap" : s.last_ok ? "bg-ok" : "bg-ember-400")} />
                  <div>
                    <a href={s.url} target="_blank" rel="noreferrer" className="font-medium hover:text-brand-700">{s.name}</a>
                    <span className="text-ink-muted"> · {s.covers}</span>
                    <div className="text-[12px] text-ink-muted">
                      {!s.enabled ? s.error : `${s.live.toLocaleString()} open now · ${s.licence}${s.last_ok ? ` · read ${ago(s.last_ok)}` : ""}`}
                      {s.enabled && s.error && <span className="text-fit-gap-ink"> · Last attempt failed: {s.error.slice(0, 140)}</span>}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="font-semibold mb-2">Not covered</div>
            <ul className="space-y-2">
              {data.not_covered.map((n: any) => <li key={n.where}><span className="font-medium">{n.where}:</span> <span className="text-ink-muted">{n.why}</span></li>)}
            </ul>
            <div className="mt-4 rounded-lg bg-paper px-3 py-2.5 text-[12.5px] text-ink-soft flex gap-2">
              <Info className="h-4 w-4 shrink-0 text-brand-600 mt-0.5" />
              <span>Fit scores compare the notice summary with your own library (capabilities, case studies, accelerators, skills and certificates). No AI is used and nothing is adjusted to look better. Read the full tender documents before deciding to bid.</span>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/** Invitations to bid from buyers in the supplier network. */
function Invitations() {
  const toast = useToast();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["invitations"], queryFn: () => api.get<any[]>("/network/invitations") });
  const act = useMutation({
    mutationFn: ({ id, what }: { id: string; what: "accept" | "decline" }) => api.post<any>(`/network/invitations/${id}/${what}`),
    onSuccess: (r, v) => {
      qc.invalidateQueries({ queryKey: ["invitations"] });
      if (v.what === "accept") { toast("ok", "Deal started from the buyer's RFP."); nav(`/app/deals/${r.deal_id}`); } else toast("ok", "Invitation declined.");
    },
    onError: (e: any) => toast("error", e.message),
  });
  if (!data?.length) return null;
  const open = data.filter((i) => i.status === "invited");
  return (
    <section className="card mb-4">
      <div className="px-5 py-3.5 border-b border-line-soft flex items-center gap-2">
        <Mail className="h-4 w-4 text-ember-600" />
        <div className="font-bold flex-1">Invitations to bid</div>
        <span className="text-[12.5px] text-ink-muted">{open.length} waiting · from buyers in the supplier network</span>
      </div>
      <ul className="divide-y divide-line-soft">
        {data.map((i) => (
          <li key={i.id} className="px-5 py-3 flex flex-wrap items-center gap-3 text-[13.5px]">
            <div className="flex-1 min-w-[280px]">
              <div className="font-semibold">{i.request.title}</div>
              <div className="text-[12.5px] text-ink-muted">{i.buyer.name} · {i.request.requirements} requirements ({i.request.mandatory} mandatory)
                {i.request.region ? ` · ${i.request.region}` : ""}{i.request.due_date ? ` · due ${i.request.due_date}` : ""} · your coverage {i.fit}%</div>
              {i.message && <div className="text-[12.5px] text-ink-soft mt-0.5">“{i.message}”</div>}
            </div>
            {i.status === "invited" ? <>
              <button className="btn-primary h-9" disabled={act.isPending} onClick={() => act.mutate({ id: i.id, what: "accept" })}>Accept and start a deal</button>
              <button className="btn-ghost h-9" disabled={act.isPending} onClick={() => act.mutate({ id: i.id, what: "decline" })}>Decline</button>
            </> : i.status === "accepted" && i.deal_id
              ? <Link to={`/app/deals/${i.deal_id}`} className="btn-outline h-9">Open the deal</Link>
              : <span className="chip bg-line-soft text-ink-muted capitalize">{i.status}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function StartDeal({ item, onClose }: { item: Item | null; onClose: () => void }) {
  const toast = useToast();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  useEffect(() => setFile(null), [item?.id]);
  const go = useMutation({
    mutationFn: (useNotice: boolean) => {
      const fd = new FormData();
      if (file && !useNotice) fd.append("file", file);
      fd.append("use_notice", String(useNotice));
      return api.upload<{ deal_id: string }>(`/radar/${item!.id}/deal`, fd);
    },
    onSuccess: (r) => { qc.invalidateQueries(); toast("ok", "Deal started. RevenueForge is reading it now."); nav(`/app/deals/${r.deal_id}`); },
    onError: (e: any) => toast("error", e.message),
  });
  return (
    <Modal open={!!item} onClose={onClose} title="Start a deal from this tender" wide>
      {item && (
        <div className="space-y-4 text-[13.5px]">
          <div><div className="font-semibold">{item.title}</div><div className="text-ink-muted">{item.buyer} · {item.country}</div></div>
          <div className="rounded-lg border border-line-soft p-4">
            <div className="font-semibold mb-1">Best: upload the tender documents</div>
            <div className="text-ink-muted mb-3">Download them from the <a className="text-brand-700 underline" href={item.url} target="_blank" rel="noreferrer">published notice</a> (registration with the buyer's portal may be needed), then add the main RFP document here.</div>
            <Dropzone accept=".pdf,.docx,.doc,.xlsx,.txt,.pptx" onFile={setFile} hint={file ? file.name : "PDF, Word, Excel or text"} />
            <button className="btn-primary mt-3" disabled={!file || go.isPending} onClick={() => go.mutate(false)}>{go.isPending && <Spinner />} Start the deal with this document</button>
          </div>
          <div className="rounded-lg border border-line-soft p-4">
            <div className="font-semibold mb-1">Quick look: start from the notice summary</div>
            <div className="text-ink-muted mb-3">Uses only the published summary, so it finds just a handful of requirements. Good for a first view; upload the full documents before you bid.</div>
            <button className="btn-outline" disabled={go.isPending} onClick={() => go.mutate(true)}>Start from the notice summary</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Detail({ id, onClose, onStart }: { id: string; onClose: () => void; onStart: (it: Item) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: t } = useQuery({ queryKey: ["radar-item", id], queryFn: () => api.get<any>(`/radar/${id}`) });
  const set = useMutation({
    mutationFn: (status: string) => api.patch(`/radar/${id}`, { status }),
    onSuccess: (_, s) => { qc.invalidateQueries({ queryKey: ["radar"] }); qc.invalidateQueries({ queryKey: ["radar-item", id] });
      toast("ok", s === "saved" ? "Saved to your shortlist." : s === "dismissed" ? "Dismissed. It won't show in the active list." : "Moved back to the active list."); },
    onError: (e: any) => toast("error", e.message),
  });
  if (!t) return <div className="card p-6"><PageLoader /></div>;
  const f = t.fit || {};
  return (
    <aside className="card lg:sticky lg:top-[72px] max-h-[calc(100vh-96px)] overflow-auto scroll-thin anim-fade-in" aria-label="Tender detail">
      <div className="flex items-start gap-2 px-5 pt-4 pb-3 border-b border-line-soft">
        <div className="min-w-0 flex-1">
          <div className="text-[12px] text-ink-muted">{t.source_name} · {t.notice_type || "Tender"}</div>
          <h2 className="font-bold text-[15.5px] leading-snug mt-0.5">{t.title}</h2>
          <div className="text-[12.5px] text-ink-muted mt-1">{t.buyer} · {t.country}{t.region && t.region !== t.country ? `, ${t.region}` : ""}</div>
        </div>
        <button className="btn-ghost h-8 px-2" onClick={onClose} aria-label="Close detail"><X className="h-4 w-4" /></button>
      </div>
      <div className="px-5 py-4 space-y-4 text-[13px]">
        <div className="grid grid-cols-3 gap-3">
          <div><div className="text-[11.5px] text-ink-muted">Fit</div><Fit score={t.score} band={t.band} /></div>
          <div><div className="text-[11.5px] text-ink-muted">Closes</div><Due iso={t.deadline} /></div>
          <div><div className="text-[11.5px] text-ink-muted">Estimated value</div><div className="num font-semibold">{t.value ? money(t.value, t.currency) : <span className="text-ink-faint font-normal">Not stated</span>}</div></div>
        </div>
        {(f.notes || []).length > 0 && (
          <ul className="space-y-1">{f.notes.map((n: string) => <li key={n} className="flex gap-2 text-ink-soft"><Info className="h-3.5 w-3.5 mt-0.5 shrink-0 text-brand-600" />{n}</li>)}</ul>
        )}
        <div>
          <div className="font-semibold mb-1.5">What matches in your library</div>
          {(f.matches || []).length ? (
            <ul className="space-y-1.5">{f.matches.map((m: any) => (
              <li key={m.type + m.name} className="flex items-center gap-2">
                <span className="text-[11.5px] text-ink-muted w-[118px] shrink-0">{m.type}</span>
                <span className="flex-1 min-w-0 truncate">{m.name}</span>
                <span className="h-1.5 w-16 rounded-full bg-line-soft overflow-hidden"><span className="block h-full bg-brand-500" style={{ width: `${Math.round(m.strength * 100)}%` }} /></span>
              </li>))}</ul>
          ) : <div className="text-ink-muted">Nothing in your library is close to this notice.</div>}
          {(f.have_tech || []).length > 0 && <div className="mt-2 text-ink-soft">Technologies you have: {f.have_tech.join(", ")}</div>}
          {(f.missing_tech || []).length > 0 && <div className="mt-1 text-fit-gap-ink">Not in your library: {f.missing_tech.join(", ")}</div>}
          {(f.missing_standards || []).length > 0 && <div className="mt-1 text-fit-gap-ink">Certificates you don't hold: {f.missing_standards.join(", ")}</div>}
        </div>
        <div>
          <div className="font-semibold mb-1.5">The notice</div>
          {t.categories?.length > 0 && <div className="flex flex-wrap gap-1 mb-2">{t.categories.slice(0, 4).map((c: any) => <span key={c.code} className="chip bg-paper border border-line text-ink-soft">{c.label || c.code}</span>)}</div>}
          <p className="text-ink-soft leading-relaxed whitespace-pre-line">{t.description ? (t.description.length > 1800 ? t.description.slice(0, 1800) + "…" : t.description) : "The source gives no description."}</p>
          <a href={t.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 font-semibold text-brand-700 hover:underline">Open the published notice <ExternalLink className="h-3.5 w-3.5" /></a>
        </div>
      </div>
      <div className="sticky bottom-0 bg-white/95 backdrop-blur border-t border-line-soft px-5 py-3 flex flex-wrap gap-2">
        {t.status === "deal" && t.deal_id ? (
          <Link to={`/app/deals/${t.deal_id}`} className="btn-primary">Open the deal</Link>
        ) : (
          <button className="btn-primary" onClick={() => onStart(t)}>Start a deal</button>
        )}
        {t.status !== "deal" && (t.status === "saved"
          ? <button className="btn-outline" onClick={() => set.mutate("new")}><Undo2 className="h-4 w-4" /> Unsave</button>
          : <button className="btn-outline" onClick={() => set.mutate("saved")}><Bookmark className="h-4 w-4" /> Save</button>)}
        {t.status !== "deal" && (t.status === "dismissed"
          ? <button className="btn-ghost" onClick={() => set.mutate("new")}><Undo2 className="h-4 w-4" /> Restore</button>
          : <button className="btn-ghost" onClick={() => set.mutate("dismissed")}><EyeOff className="h-4 w-4" /> Not for us</button>)}
      </div>
    </aside>
  );
}

const SORTS: [string, string][] = [["score", "Best fit"], ["deadline", "Closing soonest"], ["newest", "Newest"], ["value", "Largest value"]];
const FITS: [string, string][] = [["0", "Any fit"], ["35", "Possible or strong"], ["60", "Strong fit only"]];
const DUE: [string, string][] = [["0", "Any deadline"], ["14", "Closing in 14 days"], ["30", "Closing in 30 days"], ["60", "Closing in 60 days"]];
const STATUS: [string, string][] = [["active", "Active"], ["saved", "Saved"], ["deal", "Deals started"], ["dismissed", "Dismissed"]];

export default function RadarPage() {
  const [q, setQ] = useState("");
  const [qDebounced, setQD] = useState("");
  const [region, setRegion] = useState("");
  const [source, setSource] = useState("");
  const [minScore, setMin] = useState("0");
  const [due, setDue] = useState("0");
  const [status, setStatus] = useState("active");
  const [sort, setSort] = useState("score");
  const [page, setPage] = useState(0);
  const [sel, setSel] = useState<string | null>(() => new URLSearchParams(window.location.search).get("t"));
  const [starting, setStarting] = useState<Item | null>(null);
  useEffect(() => { const t = setTimeout(() => setQD(q), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => setPage(0), [qDebounced, region, source, minScore, due, status, sort]);
  const params = useMemo(() => new URLSearchParams({ q: qDebounced, region, source, min_score: minScore, due_days: due, status, sort, limit: "50", offset: String(page * 50) }).toString(),
    [qDebounced, region, source, minScore, due, status, sort, page]);
  const { data, isLoading, isFetching } = useQuery({ queryKey: ["radar", params], queryFn: () => api.get<any>(`/radar?${params}`), placeholderData: (p) => p });
  const { data: src } = useQuery({ queryKey: ["radar-sources"], queryFn: () => api.get<any>("/radar/sources") });
  const sel_ = (k: string, v: string, set: (v: string) => void, opts: [string, string][], label: string) => (
    <label className="text-[12px] text-ink-muted"><span className="sr-only">{label}</span>
      <select aria-label={label} className="input h-9 pr-8 text-[13px]" style={{ width: "auto", maxWidth: 230 }} value={v} onChange={(e) => set(e.target.value)}>{opts.map(([val, l]) => <option key={k + val} value={val}>{l}</option>)}</select>
    </label>
  );
  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1500px]">
      <div className="stagger mb-5">
        <div className="eyebrow mb-1.5">Opportunity radar</div>
        <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Public tenders you could win</h1>
        <p className="text-ink-muted text-[14px] mt-1">Open tenders from public procurement sources, scored against what your company has actually delivered.</p>
      </div>
      <Invitations />
      <Sources />
      {data && (
        <div className="mb-4">
          <StatStrip items={[
            { label: "Open tenders", value: (data.live ?? 0).toLocaleString(), sub: "Not dismissed, deadline not passed" },
            { label: "Strong fits", value: data.strong ?? 0, sub: "Score 60 or more", tone: "brand" },
            { label: "Matching your filters", value: (data.total ?? 0).toLocaleString(), sub: isFetching ? "Updating…" : " " },
            { label: "Sources live", value: src ? src.sources.filter((s: any) => s.enabled && s.last_ok).length : "—", sub: src ? `of ${src.sources.length}` : "" },
          ]} />
        </div>
      )}
      <div className="card px-3 py-2.5 mb-4 flex flex-wrap gap-2 items-center">
        <div className="relative w-full sm:w-72"><Search className="h-4 w-4 absolute left-2.5 top-2.5 text-ink-faint" />
          <input className="input h-9 pl-8" placeholder="Search title, buyer, country" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search tenders" /></div>
        {sel_("r", region, setRegion, [["", "All regions"], ...((src?.regions || []) as string[]).map((r) => [r, r] as [string, string])], "Region")}
        {sel_("s", source, setSource, [["", "All sources"], ...((src?.sources || []).filter((s: any) => s.enabled).map((s: any) => [s.key, s.name] as [string, string]))], "Source")}
        {sel_("f", minScore, setMin, FITS, "Minimum fit")}
        {sel_("d", due, setDue, DUE, "Deadline")}
        {sel_("st", status, setStatus, STATUS, "Status")}
        <div className="flex-1" />
        {sel_("so", sort, setSort, SORTS, "Sort")}
      </div>
      <div className={clsx("grid gap-4", sel ? "lg:grid-cols-[minmax(0,1fr)_460px]" : "")}>
        <div className="card overflow-x-auto min-w-0">
          {isLoading ? <PageLoader label="Scoring tenders against your library" /> : !data?.items?.length ? (
            <Empty icon={<RadarIcon className="h-8 w-8" />} title={src?.total ? "No tenders match these filters" : "No tenders read yet"}>
              {src?.total ? "Try a wider region, a lower fit or another status." : "The sources are read a minute after the server starts and then every 12 hours. An admin can also click Refresh now."}
            </Empty>
          ) : (
            <table className={clsx("w-full", sel ? "" : "min-w-[860px]")}>
              <thead><tr><th className="th w-[150px]">Fit</th><th className="th">Tender</th>{!sel && <th className="th">Where</th>}{!sel && <th className="th">Closes</th>}{!sel && <th className="th text-right">Value</th>}</tr></thead>
              <tbody>
                {data.items.map((it: Item) => (
                  <tr key={it.id} onClick={() => setSel(it.id)} className={clsx("cursor-pointer", sel === it.id ? "bg-brand-50" : "hover:bg-paper")}>
                    <td className="td align-top"><Fit score={it.score} band={it.band} />
                      {it.status !== "new" && <div className="text-[11px] mt-1 text-ink-muted">{{ deal: "Deal started", saved: "Saved", dismissed: "Dismissed" }[it.status] || it.status}</div>}</td>
                    <td className="td align-top">
                      <div className="font-semibold text-[13.5px] leading-snug line-clamp-2">{it.title}</div>
                      <div className="text-[12px] text-ink-muted mt-0.5 truncate max-w-[520px]">{sel ? `${it.country} · ${daysLeft(it.deadline) != null ? `closes in ${daysLeft(it.deadline)} days · ` : ""}` : ""}{it.buyer}{it.top_match && <> · <span className="text-brand-700">Best match: {it.top_match}</span></>}</div>
                      {it.missing_standards?.length > 0 && <div className="text-[11.5px] text-fit-gap-ink mt-0.5">Needs {it.missing_standards.join(", ")}</div>}
                    </td>
                    {!sel && <td className="td align-top text-[13px]">{it.country}<div className="text-[11.5px] text-ink-faint">{it.source_name}</div></td>}
                    {!sel && <td className="td align-top text-[13px]"><Due iso={it.deadline} /></td>}
                    {!sel && <td className="td align-top text-right num text-[13px]">{it.value ? money(it.value, it.currency) : <span className="text-ink-faint">—</span>}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data && data.total > 50 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-line-soft text-[13px]">
              <span className="text-ink-muted">{page * 50 + 1}–{Math.min(data.total, page * 50 + 50)} of {data.total.toLocaleString()}</span>
              <div className="flex gap-2">
                <button className="btn-outline h-8" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
                <button className="btn-outline h-8" disabled={(page + 1) * 50 >= data.total} onClick={() => setPage(page + 1)}>Next</button>
              </div>
            </div>
          )}
        </div>
        {sel && <Detail id={sel} onClose={() => setSel(null)} onStart={setStarting} />}
      </div>
      <StartDeal item={starting} onClose={() => setStarting(null)} />
    </div>
  );
}
