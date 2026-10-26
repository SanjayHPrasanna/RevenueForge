import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BookOpen, Boxes, CheckCircle2, ChevronLeft, ChevronRight, Circle, Download, FileText, MessageSquare, Plus, RefreshCw, Search, Upload, Users, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CatChip, Empty, MatchChip, Meter, Modal, PageLoader, RiskChip, Spinner, Stat, StatStrip, useToast } from "../components/ui";
import { Bars, CoverageMap, FitLegend, Gantt, PriceLadder, ReadinessScale, ShareBar, StatusRows, TeamBars, Waterfall } from "../components/viz";
import { useSearchParams } from "react-router-dom";
import StoryVideo, { ProposalDownload } from "../components/StoryVideo";
import { api, download } from "../lib/api";
import { CATEGORIES, ENGAGEMENT, money } from "../lib/format";
import { MatchMixBar } from "./Dashboard";
import { CommentsPanel } from "../components/Comments";
import { Clarifications } from "../components/Clarifications";

type P = { deal: any; stage: string; onChanged: () => void };

const useStage = (id: string, stage: string) => useQuery({ queryKey: ["stage", id, stage], queryFn: () => api.get(`/deals/${id}/stages/${stage}`) });
const useReqs = (id: string) => useQuery({ queryKey: ["reqs", id], queryFn: () => api.get<any[]>(`/deals/${id}/requirements`) });

// =============================================================== source viewer (traceability)
function SourcePanel({ dealId, req, onClose }: { dealId: string; req: any; onClose: () => void }) {
  const { data } = useQuery({ queryKey: ["source", dealId], queryFn: () => api.get(`/deals/${dealId}/source`), staleTime: Infinity });
  const [page, setPage] = useState(req.page);
  const ref = useRef<HTMLParagraphElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => setPage(req.page), [req.id, req.page]);
  useEffect(() => {
    const el = ref.current, c = box.current;
    if (el && c) c.scrollTo({ top: el.offsetTop - c.offsetTop - 80, behavior: "smooth" });
  }, [page, req.id, data]);
  if (!data) return <div className="card p-6"><Spinner /></div>;
  const blocks = data.blocks.filter((b: any) => b.page === page);
  return (
    <div className="card flex flex-col max-h-[calc(100vh-120px)] lg:sticky lg:top-[72px]">
      <div className="px-4 py-2.5 border-b border-line flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-brand-600" />
        <div className="text-[13px] font-semibold truncate flex-1" title={data.filename}>Source · {data.filename}</div>
        <button className="btn-ghost h-7 px-1.5" onClick={() => setPage(Math.max(1, page - 1))} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
        <span className="num text-[12px] text-ink-muted">p. {page} / {data.pages}</span>
        <button className="btn-ghost h-7 px-1.5" onClick={() => setPage(Math.min(data.pages, page + 1))} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
        <button className="btn-ghost h-7 px-1.5" onClick={onClose} aria-label="Close source"><X className="h-4 w-4" /></button>
      </div>
      <div ref={box} className="relative overflow-auto scroll-thin px-6 py-5 bg-[#FDFCFA] space-y-3">
        {blocks.length === 0 && <div className="text-sm text-ink-muted">No text on this page (it may be an image).</div>}
        {blocks.map((b: any) => {
          const hit = b.idx === req.block_idx;
          if (b.kind === "heading") return <div key={b.idx} className="font-sans font-bold text-[14px] text-ink pt-1">{b.text}</div>;
          return (
            <p key={b.idx} ref={hit ? ref : undefined}
              className={clsx("doc-text rounded px-1.5 -mx-1.5", b.kind === "bullet" && "pl-5 relative before:content-['•'] before:absolute before:left-1.5",
                b.kind === "table_row" && "font-sans text-[13px] border-l-2 border-line pl-3", hit && "bg-[#FFF6E3]")}>
              {b.ref && b.ref !== "header" && <span className="font-sans text-[11px] font-bold text-brand-700 mr-1.5">{b.ref}</span>}
              {hit ? <Highlight text={b.text} needle={req.text} /> : b.text}
            </p>
          );
        })}
      </div>
      <div className="px-4 py-2 border-t border-line text-[12px] text-ink-muted">Highlighted: where {req.source_ref || req.code} was found{req.section ? ` · ${req.section}` : ""}</div>
    </div>
  );
}

/** Side panel for a selected requirement: where it is in the RFP, and the team's discussion about it. */
function ReqSide({ dealId, req, onClose }: { dealId: string; req: any; onClose: () => void }) {
  const [tab, setTab] = useState<"source" | "talk">("source");
  return (
    <div className="min-w-0 self-start lg:sticky lg:top-[72px]">
      <div className="mb-2 flex items-center gap-1">
        <div className="inline-flex rounded-xl border border-line bg-white p-0.5 shadow-card" role="tablist" aria-label={`${req.source_ref || req.code} details`}>
          {([["source", "Source", BookOpen], ["talk", "Discussion", MessageSquare]] as const).map(([k, label, Icon]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={clsx("inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 text-[12.5px] font-semibold transition-all", tab === k ? "bg-brand-900 text-white shadow-sm" : "text-ink-soft hover:text-ink")}>
              <Icon className="h-3.5 w-3.5" /> {label}
              {k === "talk" && req.comments > 0 && <span className={clsx("num rounded-full px-1.5 text-[10.5px]", tab === k ? "bg-white/20" : "bg-ember-50 text-ember-600")}>{req.comments}</span>}
            </button>
          ))}
        </div>
        <span className="ml-2 truncate text-[12px] font-semibold text-ink-muted">{req.source_ref || req.code}</span>
        <button className="btn-ghost ml-auto h-8 px-1.5" onClick={onClose} aria-label="Close panel"><X className="h-4 w-4" /></button>
      </div>
      {tab === "source" ? <SourcePanel dealId={dealId} req={req} onClose={onClose} /> : <CommentsPanel dealId={dealId} req={req} />}
    </div>
  );
}

function Highlight({ text, needle }: { text: string; needle: string }) {
  const n = needle.replace(/^(Deliverable: |Evaluation criterion – )/, "");
  const key = n.slice(0, 50).toLowerCase();
  const i = text.toLowerCase().indexOf(key);
  if (i < 0) return <mark className="bg-[#FFE2A8] rounded-sm">{text}</mark>;
  let end = text.toLowerCase().indexOf(n.slice(-30).toLowerCase(), i);
  end = end < 0 ? Math.min(text.length, i + n.length) : end + Math.min(30, n.length);
  return <>{text.slice(0, i)}<mark className="bg-[#FFE2A8] rounded-sm px-0.5">{text.slice(i, end)}</mark>{text.slice(end)}</>;
}

// =============================================================== 1. requirements
export function RequirementsStage({ deal }: P) {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: reqs, isLoading } = useReqs(deal.id);
  const { data: st } = useStage(deal.id, "requirements");
  const { data: acc } = useQuery({ queryKey: ["acc", deal.id], queryFn: () => api.get(`/deals/${deal.id}/accuracy`) });
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [prio, setPrio] = useState("");
  const [review, setReview] = useState(false);
  const [sel, setSel] = useState<any>(null);
  const [adding, setAdding] = useState(false);
  const [labelRes, setLabelRes] = useState<any>(null);
  const upd = useMutation({
    mutationFn: ({ rid, body }: any) => api.patch(`/deals/${deal.id}/requirements/${rid}`, body),
    onSuccess: (r) => {
      qc.setQueryData(["reqs", deal.id], (old: any[]) => old?.map((x) => (x.id === r.id ? r : x)));
      qc.invalidateQueries({ queryKey: ["acc", deal.id] });
      if (sel?.id === r.id) setSel(r);
    },
    onError: (e: any) => toast("error", e.message),
  });
  const labels = useMutation({
    mutationFn: (f: File) => { const fd = new FormData(); fd.append("file", f); return api.upload(`/deals/${deal.id}/accuracy/labels`, fd); },
    onSuccess: setLabelRes,
    onError: (e: any) => toast("error", e.message),
  });
  const fileRef = useRef<HTMLInputElement>(null);
  const list = useMemo(() => (reqs || []).filter((r) =>
    (!cat || r.category === cat) && (!prio || r.priority === prio) && (!review || (r.class_confidence < 0.62 && !r.verified)) &&
    (!q || `${r.text} ${r.code} ${r.source_ref} ${r.section}`.toLowerCase().includes(q.toLowerCase()))), [reqs, q, cat, prio, review]);
  if (isLoading || !reqs) return <PageLoader />;
  const by = (c: string) => reqs.filter((r) => r.category === c).length;
  const lowConf = reqs.filter((r) => r.class_confidence < 0.62 && !r.verified).length;
  const secCount: Record<string, number> = {};
  reqs.forEach((r) => { const k = (r.section || "General").trim(); secCount[k] = (secCount[k] || 0) + 1; });
  const sections = Object.entries(secCount).sort((x, y) => y[1] - x[1]);

  return (
    <div>
      <div className="card p-5 mb-4 grid lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,0.8fr)] gap-x-8 gap-y-6">
        <div className="min-w-0">
          <div className="text-[12.5px] text-ink-muted">Requirements found</div>
          <div className="font-display num text-[34px] leading-tight text-brand-950">{reqs.length}</div>
          <div className="text-[12px] text-ink-muted mb-4">{st?.data?.pages ?? "—"} pages, {st?.data?.engine === "ai" ? "read by AI" : "read by the rules engine"}{st?.data?.learned_examples ? `, ${st.data.learned_examples} lessons from your team applied` : ""}</div>
          <div className="text-[12.5px] font-semibold text-ink-soft mb-2">By category <span className="font-normal text-ink-muted">· select one to filter</span></div>
          <div className="flex gap-[2px] h-[12px]">
            {CATEGORIES.map((c, i) => by(c) > 0 && (
              <button key={c} onClick={() => setCat(cat === c ? "" : c)} aria-label={`${c}: ${by(c)}`} className="h-full first:rounded-l last:rounded-r"
                style={{ flex: by(c), background: ["#0C3D55", "#1A82AE", "#5BA6CC", "#9FC6D9"][i], opacity: cat && cat !== c ? 0.35 : 1 }} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[12.5px]">
            {CATEGORIES.map((c, i) => (
              <button key={c} onClick={() => setCat(cat === c ? "" : c)} className={clsx("inline-flex items-center gap-1.5", cat === c ? "font-semibold text-ink" : "text-ink-soft")}>
                <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: ["#0C3D55", "#1A82AE", "#5BA6CC", "#9FC6D9"][i] }} />{c}<span className="num font-semibold text-ink">{by(c)}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="min-w-0">
          <div className="text-[12.5px] font-semibold text-ink-soft mb-3">Where they come from</div>
          <Bars rows={sections.slice(0, 6).map(([k, n]) => ({ label: k, value: n }))} format={(v) => `${v}`} color="#1A82AE"
            onPick={(label) => setQ(label)} />
        </div>
        <div className="min-w-0 lg:border-l lg:border-line-soft lg:pl-8">
          <div className="text-[12.5px] text-ink-muted">Classification accuracy</div>
          <div className="font-display num text-[34px] leading-tight text-brand-950">{acc?.accuracy != null ? `${acc.accuracy}%` : "—"}</div>
          <div className="text-[12px] text-ink-muted">{acc?.reviewed ? `${acc.correct} of ${acc.reviewed} kept after review` : "Review rows to measure it"}</div>
          <button onClick={() => setReview(!review)} className={clsx("mt-5 w-full text-left rounded-md border px-3 py-2.5", review ? "border-ember-500 bg-ember-50" : "border-line hover:border-ember-400")}>
            <div className="num text-[20px] font-bold text-ember-600 leading-none">{lowConf}</div>
            <div className="text-[12.5px] text-ink-soft mt-1">{review ? "Showing only these. Select to show all." : "Low-confidence rows to check first"}</div>
          </button>
        </div>
      </div>

      <Clarifications deal={deal} />

      <div className={clsx("grid gap-4", sel ? "lg:grid-cols-[minmax(0,1fr)_420px]" : "")}>
        <div className="card min-w-0">
          <div className="px-3 py-2.5 border-b border-line flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[180px]">
              <Search className="h-4 w-4 absolute left-2.5 top-2.5 text-ink-faint" />
              <input className="input h-9 pl-8" placeholder="Search requirements, refs, sections" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <select className="input h-9 w-auto" value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">
              <option value="">All categories</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
            <select className="input h-9 w-auto" value={prio} onChange={(e) => setPrio(e.target.value)} aria-label="Priority">
              <option value="">Any priority</option><option>Mandatory</option><option>Desirable</option>
            </select>
            <button className={clsx("btn-outline h-9", review && "border-brand-500 text-brand-700")} onClick={() => setReview(!review)}>Needs review <span className="num chip bg-ember-50 text-ember-600">{lowConf}</span></button>
            <button className="btn-ghost h-9" onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> Add</button>
          </div>
          <div className="overflow-auto scroll-thin max-h-[calc(100vh-330px)] min-h-[300px]">
            <table className={clsx("w-full", sel ? "min-w-[600px]" : "min-w-[760px]")}>
              <thead><tr><th className="th w-[84px]">Ref</th><th className="th">Requirement</th><th className="th w-[150px]">Category</th>{!sel && <th className="th w-[90px]">Priority</th>}<th className="th w-[56px] text-right">Page</th><th className="th w-[44px]"><span className="sr-only">Reviewed</span></th></tr></thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.id} onClick={() => setSel(r)} className={clsx("cursor-pointer", sel?.id === r.id ? "bg-brand-50" : "hover:bg-paper")}>
                    <td className="td num text-[12px] font-semibold text-ink-muted whitespace-nowrap">{r.source_ref || r.code}</td>
                    <td className="td">
                      <div className="text-[13.5px] leading-snug line-clamp-2">{r.text}</div>
                      <div className="text-[11.5px] text-ink-faint mt-0.5 truncate max-w-[520px]">
                        <span className={clsx("font-semibold mr-1", r.classified_by === "ai" ? "text-brand-600" : r.classified_by === "company_model" ? "text-ember-600" : r.classified_by === "human" ? "text-ok" : "text-ink-faint")}>
                          {{ ai: "AI", company_model: "Your model", human: "Edited", rules: "Rules" }[r.classified_by as string] || "Rules"}
                        </span>· {r.subcategory}{r.section ? ` · ${r.section}` : ""}
                        {r.comments > 0 && <span className="ml-2 inline-flex items-center gap-0.5 font-semibold text-brand-600"><MessageSquare className="h-3 w-3" />{r.comments}</span>}
                      </div>
                    </td>
                    <td className="td" onClick={(e) => e.stopPropagation()}>
                      <select className="input h-8 text-[12.5px] px-2" value={r.category} onChange={(e) => upd.mutate({ rid: r.id, body: { category: e.target.value } })} aria-label="Category">
                        {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
                      </select>
                      {r.class_confidence < 0.62 && !r.verified && <div className="text-[11px] text-ember-600 mt-0.5 whitespace-nowrap">Low confidence · check</div>}
                    </td>
                    {!sel && <td className="td text-[12.5px]">{r.priority}</td>}
                    <td className="td text-right num text-[12.5px] text-brand-700">p.{r.page}</td>
                    <td className="td" onClick={(e) => e.stopPropagation()}>
                      <button aria-label={r.verified ? "Reviewed" : "Mark reviewed"} title={r.verified ? "Reviewed" : "Mark reviewed"} onClick={() => upd.mutate({ rid: r.id, body: { verified: !r.verified } })}>
                        {r.verified ? <CheckCircle2 className="h-[18px] w-[18px] text-ok" /> : <Circle className="h-[18px] w-[18px] text-line" />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.length === 0 && <Empty title="No requirements match these filters" />}
          </div>
          <div className="px-4 py-2.5 border-t border-line flex flex-wrap items-center gap-3 text-[12.5px] text-ink-muted">
            <span>{list.length} shown</span>
            <div className="flex-1" />
            <input ref={fileRef} type="file" accept=".xlsx,.csv" hidden onChange={(e) => e.target.files?.[0] && labels.mutate(e.target.files[0])} />
            <button className="text-brand-700 font-semibold inline-flex items-center gap-1 hover:underline" onClick={() => fileRef.current?.click()}>
              {labels.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Upload className="h-3.5 w-3.5" />} Score against a labelled test set
            </button>
          </div>
        </div>
        {sel && <ReqSide dealId={deal.id} req={(reqs || []).find((x) => x.id === sel.id) || sel} onClose={() => setSel(null)} />}
      </div>

      <Modal open={!!labelRes} onClose={() => setLabelRes(null)} title="Accuracy against your labelled set">
        {labelRes && (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Labelled" value={labelRes.labelled} />
              <Stat label="Found (recall)" value={`${labelRes.recall}%`} />
              <Stat label="Classified right" value={`${labelRes.classification_accuracy}%`} tone="brand" />
            </div>
            {labelRes.misses.length > 0 && (
              <div className="max-h-64 overflow-auto scroll-thin text-[13px]">
                {labelRes.misses.map((m: any, i: number) => (
                  <div key={i} className="border-b border-line-soft py-2"><div className="line-clamp-2">{m.text}</div><div className="text-ink-muted text-[12px]">Label: {m.label} · RevenueForge: {m.predicted}</div></div>
                ))}
              </div>
            )}
          </div>
        )}
      </Modal>
      <AddRequirement open={adding} onClose={() => setAdding(false)} dealId={deal.id} />
    </div>
  );
}

function AddRequirement({ open, onClose, dealId }: { open: boolean; onClose: () => void; dealId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({ text: "", category: "", page: "1" });
  const add = useMutation({
    mutationFn: () => api.post(`/deals/${dealId}/requirements`, f),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["reqs", dealId] }); onClose(); setF({ text: "", category: "", page: "1" }); toast("ok", "Requirement added. Re-run matching to score it."); },
    onError: (e: any) => toast("error", e.message),
  });
  return (
    <Modal open={open} onClose={onClose} title="Add a requirement">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
        <div><label className="label">Requirement</label><textarea className="input h-24 py-2" required value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label">Category</label><select className="input" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}><option value="">Classify automatically</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></div>
          <div><label className="label">Page</label><input className="input num" type="number" min={1} value={f.page} onChange={(e) => setF({ ...f, page: e.target.value })} /></div>
        </div>
        <button className="btn-primary" disabled={add.isPending}>Add requirement</button>
      </form>
    </Modal>
  );
}

// =============================================================== 2. matching
const EV_ICON: Record<string, any> = { Capability: Boxes, "Case study": FileText, Accelerator: RefreshCw, Certification: CheckCircle2 };

export function MatchingStage({ deal }: P) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: reqs } = useReqs(deal.id);
  const [params] = useSearchParams();
  const [tab, setTab] = useState(params.get("status") || "all");
  const [cat, setCat] = useState(params.get("cat") || "");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<any>(null);
  useEffect(() => {
    const rid = params.get("r");
    if (rid && reqs && !sel) setSel(reqs.find((r) => r.id === rid) || null);
  }, [reqs]);
  const upd = useMutation({
    mutationFn: ({ rid, body }: any) => api.patch(`/deals/${deal.id}/requirements/${rid}`, body),
    onSuccess: (r) => qc.setQueryData(["reqs", deal.id], (old: any[]) => old?.map((x) => (x.id === r.id ? r : x))),
    onError: (e: any) => toast("error", e.message),
  });
  if (!reqs) return <PageLoader />;
  const mix: Record<string, number> = {};
  reqs.forEach((r) => (mix[r.match_status] = (mix[r.match_status] || 0) + 1));
  const list = reqs.filter((r) => (tab === "all" ? (cat ? true : r.category !== "Commercial") : r.match_status === tab) && (!cat || r.category === cat) &&
    (!q || r.text.toLowerCase().includes(q.toLowerCase())));
  const byCat = CATEGORIES.map((c) => {
    const counts: Record<string, number> = {};
    reqs.filter((r) => r.category === c).forEach((r) => (counts[r.match_status] = (counts[r.match_status] || 0) + 1));
    return { label: c, counts };
  }).filter((r) => Object.keys(r.counts).length);
  return (
    <div className={clsx("grid gap-4", sel ? "lg:grid-cols-[minmax(0,1fr)_440px]" : "")}>
      <div className="min-w-0">
        <div className={clsx("card p-5 mb-4 grid gap-x-8 gap-y-6", sel ? "" : "xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]")}>
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-3 mb-2"><div className="font-bold">Coverage map</div><div className="text-[12.5px] text-ink-muted">Select a tile to open its evidence.</div></div>
            <FitLegend counts={mix} className="mb-3" active={tab} onPick={(k) => setTab(tab === k ? "all" : k)} />
            <CoverageMap reqs={reqs} compact onPick={setSel} selected={sel?.id} />
          </div>
          {!sel && (
            <div className="min-w-0 xl:border-l xl:border-line-soft xl:pl-8">
              <div className="font-bold mb-1">By category</div>
              <div className="text-[12.5px] text-ink-muted mb-4">Scored on your capabilities, case studies, accelerators, certifications and people's skills. Select a bar to filter.</div>
              <StatusRows rows={byCat} onPick={(c, st) => { setCat(c); setTab(st); }} />
            </div>
          )}
        </div>
        <div className="card">
          <div className="px-3 py-2.5 border-b border-line flex flex-wrap gap-2 items-center">
            {[["all", "Technical & compliance"], ["strong", "Strong"], ["partial", "Partial"], ["gap", "Gaps"], ["confirm", "To confirm"]].map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)} className={clsx("btn h-8 px-3", tab === k ? "bg-brand-900 text-white" : "text-ink-soft hover:bg-line-soft")}>
                {k === "all" && cat ? "All" : l} {k !== "all" && <span className="num opacity-80">{mix[k] || 0}</span>}
              </button>
            ))}
            {cat && <button className="chip bg-brand-50 text-brand-700 h-7 px-2" onClick={() => setCat("")}>{cat} <X className="h-3 w-3" /></button>}
            <div className="flex-1" />
            <div className="relative w-full sm:w-64"><Search className="h-4 w-4 absolute left-2.5 top-2.5 text-ink-faint" /><input className="input h-9 pl-8" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          </div>
          <ul className="divide-y divide-line-soft max-h-[calc(100vh-380px)] min-h-[300px] overflow-auto scroll-thin">
            {list.map((r) => (
              <li key={r.id} className={clsx("px-4 py-3.5 cursor-pointer", sel?.id === r.id ? "bg-brand-50" : "hover:bg-paper")} onClick={() => setSel(r)}>
                <div className="flex gap-3">
                  <div className="w-[70px] shrink-0">
                    <div className="num text-[12px] font-semibold text-ink-muted">{r.source_ref || r.code}</div>
                    <div className="mt-1"><MatchChip status={r.match_status} /></div>
                    {r.match_status !== "confirm" && <div className="num text-[11.5px] text-ink-faint mt-1">{Math.round(r.match_score * 100)}%</div>}
                    {r.match?.judged_by === "ai" && <div className="text-[10.5px] font-semibold text-brand-600 mt-0.5">AI judged</div>}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] leading-snug">{r.text}</div>
                    <div className="text-[12.5px] text-ink-muted mt-1.5">{r.match?.rationale}</div>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {(r.match?.evidence || []).slice(0, 3).map((e: any, i: number) => {
                        const I = EV_ICON[e.type] || Boxes;
                        return <span key={i} className="chip bg-paper border border-line text-ink-soft font-medium"><I className="h-3 w-3 text-brand-600" />{e.name}</span>;
                      })}
                      {r.match?.people_count > 0 && <span className="chip bg-paper border border-line text-ink-soft font-medium"><Users className="h-3 w-3 text-brand-600" />{r.match.people_count} people</span>}
                      {(r.match?.technologies_missing || []).map((t: string) => <span key={t} className="chip bg-[#FBE7E5] text-fit-gap-ink">Missing: {t}</span>)}
                    </div>
                  </div>
                  <div onClick={(e) => e.stopPropagation()} className="shrink-0">
                    <select className="input h-8 text-[12.5px] w-[110px]" value={r.match_status} onChange={(e) => upd.mutate({ rid: r.id, body: { match_status: e.target.value } })} aria-label="Override match">
                      <option value="strong">Strong</option><option value="partial">Partial</option><option value="gap">Gap</option><option value="confirm">Confirm</option>
                    </select>
                    {r.match?.overridden_by && <div className="text-[11px] text-ink-faint mt-1">Set by {r.match.overridden_by}</div>}
                  </div>
                </div>
              </li>
            ))}
            {list.length === 0 && <Empty title="Nothing in this view" />}
          </ul>
        </div>
      </div>
      {sel && <ReqSide dealId={deal.id} req={(reqs || []).find((x) => x.id === sel.id) || sel} onClose={() => setSel(null)} />}
    </div>
  );
}

// =============================================================== 3. gaps
const OPT_STYLE: Record<string, string> = {
  Partner: "bg-[#EEF0FB] text-[#4A54A8]", Upskill: "bg-brand-50 text-brand-700", Hire: "bg-ember-50 text-ember-600",
  Certify: "bg-[#F3ECF8] text-[#7A3E9A]", Build: "bg-line-soft text-ink-soft", "Strengthen evidence": "bg-ok-bg text-ok", "Define method": "bg-ok-bg text-ok",
};
const FIX_LABEL: Record<string, string> = {
  Partner: "Bring in a partner", Upskill: "Upskill the team", Hire: "Hire", Certify: "Get certified", Build: "Build it",
  "Strengthen evidence": "Strengthen evidence", "Define method": "Define the method",
};
export function GapsStage({ deal }: P) {
  const { data: st } = useStage(deal.id, "gaps");
  const { data: reqs } = useReqs(deal.id);
  const [params] = useSearchParams();
  const [risk, setRisk] = useState("");
  const [fix, setFix] = useState(params.get("fix") || "");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (!st || !reqs) return <PageLoader />;
  const g = st.data;
  const all = reqs.filter((r) => r.gap?.risk);
  const items = all.filter((r) => (!risk || r.gap.risk === risk) && (!fix || r.gap.recommended === fix));
  const fixes: Record<string, number> = {};
  all.forEach((r) => (fixes[r.gap.recommended] = (fixes[r.gap.recommended] || 0) + 1));
  const groups = new Map<string, any[]>();
  items.forEach((r) => { const k = r.gap.recommended || "Other"; if (!groups.has(k)) groups.set(k, []); groups.get(k)!.push(r); });
  const order = ["High", "Medium", "Low"];
  const ordered = [...groups.entries()].sort((x, y) => y[1].length - x[1].length);
  return (
    <div className="space-y-4">
      <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)] gap-4">
        <div className="card p-5">
          <div className="text-[12.5px] text-ink-muted">Bid recommendation</div>
          <div className="font-display text-[28px] leading-tight text-brand-950 mt-0.5">{g.verdict}</div>
          <div className="mt-5"><ReadinessScale today={g.readiness} mitigated={g.mitigated_readiness} /></div>
          <div className="mt-3 text-[12.5px] text-ink-muted leading-relaxed">
            {g.coverage_pct}% of mandatory requirements are covered by what you have today. {g.high_risk} high-risk gaps{g.partner_led ? `, ${g.partner_led} best closed with a partner` : ""}.
          </div>
        </div>
        <div className="card p-5">
          <div className="font-bold">Fix by type</div>
          <div className="text-[12.5px] text-ink-muted mb-4">Select one to show only those requirements.</div>
          <Bars rows={Object.entries(fixes).sort((x, y) => y[1] - x[1]).map(([k, n]) => ({ label: FIX_LABEL[k] || k, value: n }))} format={(v) => `${v}`} color="#0C3D55"
            highlight={fix ? FIX_LABEL[fix] || fix : undefined}
            onPick={(label) => { const k = Object.keys(fixes).find((x) => (FIX_LABEL[x] || x) === label) || ""; setFix(fix === k ? "" : k); }} />
        </div>
        <div className="card p-5">
          <div className="font-bold">Missing from your library</div>
          <div className="text-[12.5px] text-ink-muted mb-4">Technologies and certifications the RFP names.</div>
          {g.top_missing.length === 0 ? <div className="text-[13px] text-ink-muted">Nothing. Every technology the RFP names is in your library.</div> : (
            <ul className="space-y-2.5">
              {g.top_missing.map((t: any) => (
                <li key={t.technology} className="flex items-center gap-3 text-[13.5px]">
                  <span className="font-semibold flex-1 min-w-0 truncate">{t.technology}</span>
                  <span className="text-[12px] text-ink-muted num">{t.requirements} req</span>
                  <span className={clsx("chip", OPT_STYLE[t.recommendation])}>{t.recommendation}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card">
        <div className="px-4 py-2.5 border-b border-line flex flex-wrap gap-2 items-center">
          <div className="font-bold mr-2">Mitigation plan</div>
          {["", ...order].map((k) => (
            <button key={k || "all"} onClick={() => setRisk(k)} className={clsx("btn h-8 px-3", risk === k ? "bg-brand-900 text-white" : "text-ink-soft hover:bg-line-soft")}>
              {k ? `${k} risk` : "All risks"} <span className="num opacity-80">{k ? g.risk_counts?.[k] ?? 0 : all.length}</span>
            </button>
          ))}
          {fix && <button className="chip bg-brand-50 text-brand-700 h-7 px-2" onClick={() => setFix("")}>{FIX_LABEL[fix] || fix} <X className="h-3 w-3" /></button>}
        </div>
        {ordered.length === 0 && <Empty title="Nothing in this view" />}
        {ordered.map(([k, rs]) => {
          // the advice most rows in this group share is shown once, in the group header
          const freq: Record<string, number> = {};
          rs.forEach((r) => { const d = r.gap.options[0]?.detail || ""; freq[d] = (freq[d] || 0) + 1; });
          const common = Object.entries(freq).sort((x, y) => y[1] - x[1])[0];
          const shared = common && common[1] >= 3 ? common[0] : "";
          const first = rs[0].gap.options[0] || {};
          const sorted = [...rs].sort((x, y) => order.indexOf(x.gap.risk) - order.indexOf(y.gap.risk));
          const isOpen = open[k] ?? ordered.length <= 2;
          const shown = isOpen ? sorted : sorted.slice(0, 4);
          return (
            <section key={k} className="border-b border-line last:border-0">
              <div className="px-4 py-3.5 bg-[#F8FAFB] flex flex-wrap items-start gap-x-4 gap-y-1">
                <div className="flex-1 min-w-[220px]">
                  <div className="font-semibold text-[14px]">{FIX_LABEL[k] || k} <span className="text-ink-muted font-normal num">· {rs.length} requirement{rs.length === 1 ? "" : "s"}</span></div>
                  {shared && <div className="text-[13px] text-ink-soft mt-0.5">{shared}</div>}
                </div>
                {first.effort && <div className="text-[12px] text-ink-muted">{first.effort} · {first.cost} cost</div>}
              </div>
              <ul className="divide-y divide-line-soft">
                {shown.map((r) => {
                  const o = r.gap.options[0] || {};
                  return (
                    <li key={r.id} className="px-4 py-3 grid md:grid-cols-[96px_minmax(0,1fr)_minmax(0,0.8fr)] gap-x-4 gap-y-1">
                      <div className="flex md:flex-col gap-1.5 items-start">
                        <span className="num text-[12px] font-semibold text-ink-muted">{r.source_ref || r.code}</span>
                        <RiskChip risk={r.gap.risk} />
                      </div>
                      <div className="text-[13.5px] leading-snug">{r.text}<div className="mt-1 flex items-center gap-2"><MatchChip status={r.match_status} /><span className="text-[12px] text-ink-faint">p.{r.page}</span></div></div>
                      <div className="text-[13px] text-ink-soft">
                        {o.detail && o.detail !== shared && <div>{o.detail}</div>}
                        {r.gap.options.length > 1 && <div className="text-[12px] text-ink-muted mt-1">Alternatives: {r.gap.options.slice(1).map((x: any) => x.type).join(", ")}</div>}
                      </div>
                    </li>
                  );
                })}
              </ul>
              {sorted.length > 4 && (
                <button className="w-full px-4 py-2.5 text-left text-[13px] font-semibold text-brand-700 hover:bg-paper border-t border-line-soft" onClick={() => setOpen({ ...open, [k]: !isOpen })}>
                  {isOpen ? "Show fewer" : `Show all ${sorted.length}`}
                </button>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

// =============================================================== 4. architecture
const SRC_STYLE: Record<string, string> = {
  "RFP-mandated": "border-brand-500 bg-brand-50 text-brand-900",
  Proposed: "border-line bg-white text-ink",
  "Client-owned": "border-dashed border-ink-faint bg-paper text-ink-soft",
  "Partner product": "border-[#8C93D8] bg-[#EEF0FB] text-[#353D8C]",
  "Assessment scope": "border-brand-200 bg-white text-ink",
};
export function ArchitectureStage({ deal }: P) {
  const { data: st } = useStage(deal.id, "architecture");
  if (!st) return <PageLoader />;
  const a = st.data;
  return (
    <div className="space-y-4">
      <div className="card p-5 text-[14.5px] leading-relaxed text-ink-soft">
        <span className={clsx("chip mr-2", a.engine === "ai" ? "bg-brand-50 text-brand-700" : "bg-line-soft text-ink-muted")}>{a.engine === "ai" ? "AI-designed" : "Rules draft"}</span>{a.summary}
      </div>
      <div className="card p-4 md:p-5">
        <div className="flex flex-wrap gap-3 mb-4 text-[12px]">
          {Object.entries(SRC_STYLE).filter(([k]) => a.style === "ea-domains" ? k === "Assessment scope" : k !== "Assessment scope").map(([k, v]) => (
            <span key={k} className="inline-flex items-center gap-1.5"><span className={clsx("h-3 w-5 rounded-sm border-2", v)} />{k}</span>
          ))}
        </div>
        <div className="space-y-2">
          {a.layers.map((l: any) => (
            <div key={l.layer} className="grid md:grid-cols-[200px_1fr] gap-2 md:gap-3 items-stretch">
              <div className="rounded-md border-l-4 border-brand-800 bg-brand-50 text-brand-950 text-[13px] font-semibold px-3 py-2.5 flex items-center justify-between gap-2">
                <span>{l.layer}</span><span className="num text-[11px] font-medium text-ink-muted">{l.components.length}</span>
              </div>
              <div className="rounded-md bg-paper border border-line-soft p-2 flex flex-wrap gap-2">
                {l.components.map((c: any) => (
                  <div key={c.name} className={clsx("rounded border-2 px-2.5 py-1.5 text-[12.5px] font-semibold", SRC_STYLE[c.source] || SRC_STYLE.Proposed)}
                    title={c.requirements.length ? `Driven by ${c.requirements.join(", ")}` : c.source}>
                    {c.name}
                    {c.requirements.length > 0 && <span className="ml-1.5 num text-[10.5px] font-medium opacity-70">{c.requirements.length} req</span>}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="card overflow-x-auto">
        <div className="px-5 py-3.5 border-b border-line font-bold">Technology decisions</div>
        <table className="w-full min-w-[720px]">
          <thead><tr><th className="th">Area</th><th className="th">Choice</th><th className="th">Basis</th><th className="th">Rationale</th><th className="th">Driven by</th></tr></thead>
          <tbody>
            {a.choices.map((c: any) => (
              <tr key={c.area}><td className="td font-semibold">{c.area}</td><td className="td">{c.choice}</td><td className="td text-[13px]">{c.basis}</td><td className="td text-[13px] text-ink-soft">{c.rationale}</td><td className="td text-[12px] num text-ink-muted">{(c.requirements || []).slice(0, 5).join(", ")}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// =============================================================== 5. estimation
function Overrides({ deal, stage, fields, current, defaults = {} }: { deal: any; stage: string; fields: { key: string; label: string; suffix?: string; step?: number }[]; current: any; defaults?: Record<string, any> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [v, setV] = useState<Record<string, any>>({});
  useEffect(() => setV(Object.fromEntries(fields.map((f) => [f.key, current[f.key] ?? ""]))), [JSON.stringify(current)]);
  const save = useMutation({
    mutationFn: () => api.put(`/deals/${deal.id}/stages/${stage}/overrides`, { overrides: v }),
    onSuccess: () => { qc.invalidateQueries(); toast("ok", "Recalculated. The proposal is being refreshed."); },
    onError: (e: any) => toast("error", e.message),
  });
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {fields.map((f) => (
        <label key={f.key} className="text-[12.5px]">
          <span className="text-ink-soft font-medium">{f.label}</span>
          <div className="relative mt-1">
            <input className="input h-9 w-28 num pr-8" type="number" step={f.step ?? "any"} placeholder={defaults[f.key] != null ? String(defaults[f.key]) : ""} value={v[f.key] ?? ""} onChange={(e) => setV({ ...v, [f.key]: e.target.value === "" ? "" : Number(e.target.value) })} />
            {f.suffix && <span className="absolute right-2.5 top-2 text-ink-faint text-[12px]">{f.suffix}</span>}
          </div>
        </label>
      ))}
      <button className="btn-dark h-9" disabled={save.isPending}>{save.isPending && <Spinner />} Recalculate</button>
    </form>
  );
}

export function EstimationStage({ deal }: P) {
  const { data: st } = useStage(deal.id, "estimation");
  if (!st) return <PageLoader />;
  const e = st.data;
  const totalWeeks = Math.max(...e.phases.map((p: any) => p.weeks + (p.parallel ? e.phases[0].weeks : 0)), 1);
  let cursor = 0;
  const isMS = e.engagement_type === "managed_services";
  return (
    <div className="space-y-4">
      <StatStrip items={[
        { label: isMS ? "Contract term" : "Duration", value: `${e.contract_months} months`, sub: ENGAGEMENT[e.engagement_type] },
        { label: "Team", value: `${e.headcount} people`, sub: `${e.fte} FTE, ${Math.round(e.onsite_ratio * 100)}% onsite` },
        { label: "Effort", value: `${Math.round(e.total_person_days).toLocaleString()}`, sub: "person-days" },
        { label: "Contingency", value: `${e.contingency_pct}%`, sub: "From gap risk" },
        { label: "Unfilled roles", value: e.unfilled_roles, sub: e.unfilled_roles ? "Hire or contract" : "Every role has a name", tone: e.unfilled_roles ? "gap" : undefined },
      ]} />
      <div className="card p-5">
        <div className="flex flex-wrap items-end gap-3 mb-5">
          <div className="flex-1 min-w-[200px]"><div className="font-bold">Plan</div><div className="text-[12.5px] text-ink-muted">Change the term, onsite share or contingency and everything downstream recalculates.</div></div>
          <Overrides deal={deal} stage="estimation" current={e.overrides || {}} defaults={{ contract_months: e.contract_months, duration_months: e.duration_months, onsite_ratio: e.onsite_ratio, contingency_pct: e.contingency_pct }} fields={[
            { key: isMS ? "contract_months" : "duration_months", label: isMS ? "Contract months" : "Duration months" },
            { key: "onsite_ratio", label: "Onsite share (0–1)", step: 0.05 },
            { key: "contingency_pct", label: "Contingency", suffix: "%" },
          ]} />
        </div>
        <Gantt months={Math.max(1, Math.round(totalWeeks / 4.33))} phases={e.phases.map((ph: any) => {
          const start = ph.parallel ? e.phases[0].weeks : cursor;
          if (!ph.parallel) cursor += ph.weeks;
          return { name: ph.name, detail: ph.detail, start: start / 4.33, end: (start + ph.weeks) / 4.33 };
        })} />
      </div>
      <div className="grid xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4">
        <div className="card p-5">
          <div className="font-bold">Team shape</div>
          <div className="text-[12.5px] text-ink-muted mb-4">Full-time equivalents per role.</div>
          <TeamBars team={e.team} />
        </div>
        <div className="card p-5">
          <div className="font-bold">Effort by workstream</div>
          <div className="text-[12.5px] text-ink-muted mb-4">Person-days to deliver the requirements in each workstream.</div>
          <Bars rows={e.workstreams.map((w: any) => ({ label: w.name, value: w.effort_days, sub: `· ${w.requirements} req`,
            tip: <div><b>{w.name}</b><div>{w.requirements} requirements, {Math.round(w.effort_days)} person-days</div><div className="opacity-70">{Object.entries(w.complexity).map(([k, n]) => `${n} ${String(k).toLowerCase()}`).join(", ")} complexity</div></div> }))}
            format={(v) => `${Math.round(v)} d`} />
          {e.accelerators?.length > 0 && <div className="mt-4 pt-3 border-t border-line-soft text-[12px] text-ink-muted">Accelerators applied: {e.accelerators.map((a: any) => a.name).join(", ")} (−{e.accelerator_saving_pct}% effort)</div>}
        </div>
      </div>
      <div className="card overflow-x-auto">
        <div className="px-5 py-3.5 border-b border-line"><div className="font-bold">Who's on the team</div><div className="text-[12.5px] text-ink-muted">Matched from your skills matrix on role, skills ({e.staffing_skills.slice(0, 4).join(", ")}) and availability. Orange: on another project now.</div></div>
        <table className="w-full min-w-[640px]">
          <thead><tr><th className="th">Role</th><th className="th text-right">FTE</th><th className="th">Location</th><th className="th">Proposed people</th></tr></thead>
          <tbody>
            {e.team.map((t: any, i: number) => (
              <tr key={i}>
                <td className="td"><div className="font-semibold text-[13.5px]">{t.role}</div><div className="text-[12px] text-ink-muted">{t.responsibility}</div></td>
                <td className="td text-right num">{t.fte}</td>
                <td className="td text-[13px]">{t.location}</td>
                <td className="td">
                  <div className="flex flex-wrap gap-1">
                    {t.assigned.map((pp: any) => (
                      <span key={pp.code} className={clsx("chip border", pp.status === "Available" ? "bg-white border-line text-ink-soft" : "bg-ember-50 border-ember-100 text-ember-600")}
                        title={`${pp.role}, ${pp.level}, ${pp.location}, ${pp.availability}% available`}>{pp.code}</span>
                    ))}
                    {t.unfilled > 0 && <span className="chip bg-[#FBE7E5] text-fit-gap-ink">+{t.unfilled} to hire</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card p-5"><div className="font-bold mb-2">Assumptions</div><ul className="list-disc pl-5 text-[13.5px] text-ink-soft space-y-1">{e.assumptions.map((a: string) => <li key={a}>{a}</li>)}</ul></div>
    </div>
  );
}

// =============================================================== 6. pricing
export function PricingStage({ deal }: P) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: st } = useStage(deal.id, "pricing");
  const [ccyView, setCcyView] = useState<"rfp" | "base">("rfp");
  const pick = useMutation({
    mutationFn: (name: string) => api.put(`/deals/${deal.id}/stages/pricing/overrides`, { selected: name }),
    onSuccess: () => { qc.invalidateQueries(); toast("ok", "Scenario selected. The proposal is being refreshed."); },
    onError: (e: any) => toast("error", e.message),
  });
  if (!st) return <PageLoader />;
  const p = st.data;
  const fx = ccyView === "rfp" ? p.fx_to_rfp : 1;
  const ccy = ccyView === "rfp" ? p.rfp_currency : p.currency;
  const m = (v: number) => money(v * fx, ccy);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-[13px] text-ink-muted">Show in</div>
        <div className="inline-flex rounded-md border border-line bg-white p-0.5">
          {(["rfp", "base"] as const).map((k) => (
            <button key={k} onClick={() => setCcyView(k)} className={clsx("px-3 h-7 rounded text-[12.5px] font-semibold", ccyView === k ? "bg-brand-900 text-white" : "text-ink-soft")}>
              {k === "rfp" ? `${p.rfp_currency} (RFP)` : `${p.currency} (rate card)`}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <Overrides deal={deal} stage="pricing" current={p.overrides || {}} defaults={{ target_margin: p.target_margin, contingency_pct: p.contingency_pct, travel_pct: p.travel_pct }} fields={[
          { key: "target_margin", label: "Target margin", suffix: "%" },
          { key: "contingency_pct", label: "Contingency", suffix: "%" },
          { key: "travel_pct", label: "Travel", suffix: "%" },
        ]} />
      </div>
      <div className="card p-5">
        <div className="font-bold">Price against cost</div>
        <div className="text-[12.5px] text-ink-muted mb-3">Each option on one scale with your total cost and your {p.min_margin}% margin floor. Select an option to put it in the proposal.</div>
        <PriceLadder cost={p.total_cost} floorMargin={p.min_margin} scenarios={p.scenarios} selected={p.selected || "Target"} list={p.list_price} fmt={m}
          onPick={(name) => name !== (p.selected || "Target") && pick.mutate(name)} />
      </div>
      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {p.scenarios.map((s: any) => {
          const active = (p.selected || "Target") === s.name;
          const below = s.margin_pct < p.min_margin;
          return (
            <button key={s.name} onClick={() => !active && pick.mutate(s.name)} className={clsx("card p-4 text-left transition-shadow", active ? "ring-2 ring-ember-500" : "hover:shadow-lift")}>
              <div className="flex items-center gap-2">
                <span className={clsx("h-4 w-4 rounded-full border-2 grid place-items-center", active ? "border-ember-500" : "border-line")}>{active && <span className="h-2 w-2 rounded-full bg-ember-500" />}</span>
                <span className="font-bold">{s.name}</span>
                {active && <span className="chip bg-ember-50 text-ember-600 ml-auto">In proposal</span>}
              </div>
              <div className="font-display num text-[26px] leading-tight mt-2 text-brand-950">{m(s.price)}</div>
              <div className="text-[12.5px] text-ink-muted mt-0.5"><span className={clsx("num font-semibold", below ? "text-fit-gap-ink" : "text-ink")}>{s.margin_pct}% margin</span>, {s.vs_list_pct > 0 ? "+" : ""}{s.vs_list_pct}% vs rate card</div>
              <div className="text-[12px] text-ink-muted mt-1">{s.note}</div>
            </button>
          );
        })}
      </div>
      <div className="grid xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-4">
        <div className="card p-5">
          <div className="font-bold">From cost to price</div>
          <div className="text-[12.5px] text-ink-muted mb-2">How the {p.selected || "Target"} price builds up.</div>
          {(() => {
            const sel = p.scenarios.find((x: any) => x.name === (p.selected || "Target")) || p.scenarios[0];
            return <Waterfall fmt={m} steps={[
              { label: "Labour", value: p.labour_cost, kind: "add" }, { label: "Travel", value: p.travel, kind: "add" },
              { label: "Contingency", value: p.contingency, kind: "add" }, { label: "Total cost", value: p.total_cost, kind: "total" },
              { label: "Margin", value: sel.price - p.total_cost, kind: "margin" }, { label: "Price", value: sel.price, kind: "total" },
            ]} />;
          })()}
        </div>
        <div className="space-y-4">
          <div className="card p-5">
            <div className="font-bold mb-3">Payment milestones</div>
            {(() => {
              const sel = p.scenarios.find((x: any) => x.name === (p.selected || "Target")) || p.scenarios[0];
              return <ShareBar fmt={m} parts={p.milestones.map((ms: any, i: number) => ({ label: ms.name, value: (sel.price * ms.pct) / 100, color: ["#0C3D55", "#1A82AE", "#5BA6CC", "#9FC6D9", "#C9DEE9"][i % 5] }))} />;
            })()}
          </div>
          <div className="card p-5 text-[13px] text-ink-soft space-y-1.5">
            <div className="font-bold text-ink text-[14px] mb-1">Assumptions</div>
            {p.assumptions.map((a: string) => <div key={a}>{a}</div>)}
            {p.partner_note && <div className="text-ember-600">{p.partner_note}</div>}
            <div>Margin floor: {p.min_margin}% (set in Settings).</div>
          </div>
        </div>
      </div>
      <div className="card overflow-x-auto">
        <div className="px-5 py-3.5 border-b border-line font-bold">Cost build-up by role</div>
        <table className="w-full min-w-[640px]">
          <thead><tr><th className="th">Role</th><th className="th">Location</th><th className="th text-right">Days</th><th className="th text-right">Day rate</th><th className="th text-right">Day cost</th><th className="th text-right">Cost</th></tr></thead>
          <tbody>
            {p.lines.map((l: any, i: number) => (
              <tr key={i}>
                <td className="td text-[13.5px]">{l.role}<div className="text-[11px] text-ink-faint">{l.rate_source}</div></td><td className="td text-[13px]">{l.location}</td>
                <td className="td text-right num">{Math.round(l.person_days).toLocaleString()}</td><td className="td text-right num">{m(l.day_rate)}</td>
                <td className="td text-right num text-ink-muted">{m(l.day_cost)}</td><td className="td text-right num font-semibold">{m(l.cost)}</td>
              </tr>
            ))}
            <tr><td className="td" colSpan={5}>Labour</td><td className="td text-right num font-semibold">{m(p.labour_cost)}</td></tr>
            <tr><td className="td" colSpan={5}>Travel and living ({p.travel_pct}% of onsite)</td><td className="td text-right num">{m(p.travel)}</td></tr>
            <tr><td className="td" colSpan={5}>Contingency ({p.contingency_pct}%)</td><td className="td text-right num">{m(p.contingency)}</td></tr>
            <tr className="bg-paper"><td className="td font-bold" colSpan={5}>Total cost</td><td className="td text-right num font-bold">{m(p.total_cost)}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

// =============================================================== 7. proposal
const SRC: Record<string, [string, string]> = {
  library: ["From your library", "bg-ok-bg text-ok"], ai: ["AI draft", "bg-brand-50 text-brand-700"],
  human: ["Team-written", "bg-ember-50 text-ember-600"], rules: ["Template", "bg-line-soft text-ink-muted"],
};

function ResponseRow({ dealId, r, onSaved }: { dealId: string; r: any; onSaved: () => void }) {
  const toast = useToast();
  const [v, setV] = useState(r.response || "");
  const [dirty, setDirty] = useState(false);
  useEffect(() => { setV(r.response || ""); setDirty(false); }, [r.id, r.response]);
  const save = useMutation({
    mutationFn: () => api.patch(`/deals/${dealId}/requirements/${r.id}`, { response: v }),
    onSuccess: () => { setDirty(false); onSaved(); toast("ok", "Answer saved. RevenueForge will learn from this rewrite."); },
    onError: (e: any) => toast("error", e.message),
  });
  const src = SRC[r.response_source] || SRC.rules;
  return (
    <li className="px-4 py-3.5 grid lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.3fr)] gap-3">
      <div>
        <div className="flex items-center gap-2"><span className="num text-[12px] font-semibold text-ink-muted">{r.source_ref || r.code}</span><MatchChip status={r.match_status} /><span className={clsx("chip", src[1])}>{src[0]}</span></div>
        <div className="text-[13px] text-ink-soft mt-1.5 leading-snug">{r.text}</div>
      </div>
      <div>
        <textarea className="input h-auto min-h-[84px] py-2 text-[13.5px] leading-snug" value={v} onChange={(e) => { setV(e.target.value); setDirty(true); }} aria-label={`Answer for ${r.code}`} />
        {dirty && <div className="flex gap-2 mt-1.5"><button className="btn-primary h-8" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending && <Spinner />} Save answer</button><button className="btn-ghost h-8" onClick={() => { setV(r.response || ""); setDirty(false); }}>Cancel</button></div>}
      </div>
    </li>
  );
}

export function ProposalStage({ deal }: P) {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: st } = useStage(deal.id, "proposal");
  const { data: reqs } = useReqs(deal.id);
  const [edited, setEdited] = useState(false);
  const [filter, setFilter] = useState("all");
  const regen = useMutation({ mutationFn: () => api.post(`/deals/${deal.id}/rerun`, { from_stage: "proposal" }), onSuccess: () => qc.invalidateQueries() });
  const rebuild = useMutation({
    mutationFn: () => api.post(`/deals/${deal.id}/proposal/rebuild`),
    onSuccess: () => { setEdited(false); toast("ok", "Proposal document updated with your edits."); },
    onError: (e: any) => toast("error", e.message),
  });
  if (!st || !reqs) return <PageLoader />;
  const d = st.data;
  const answers = reqs.filter((r) => r.response && (filter === "all" || r.response_source === filter));
  const counts: Record<string, number> = {};
  reqs.filter((r) => r.response).forEach((r) => (counts[r.response_source] = (counts[r.response_source] || 0) + 1));
  return (
    <div className="space-y-4">
      <div className="grid lg:grid-cols-[minmax(0,1fr)_320px] gap-4">
        <article className="card px-6 md:px-12 py-10 bg-[#FDFCFA]">
          <div className="font-sans text-[12px] font-semibold text-brand-700">Executive summary</div>
          <h3 className="font-display text-[28px] leading-tight text-brand-950 mt-1 mb-5">{deal.name}</h3>
          <div className="doc-text space-y-4 max-w-[68ch]">{(d.executive_summary || "").split("\n\n").map((p: string, i: number) => <p key={i}>{p}</p>)}</div>
        </article>
        <aside className="space-y-4">
          <div className="card p-5">
            <div className="font-bold">Proposal document</div>
            <div className="text-[13px] text-ink-muted mt-1">Written into your Word template: {d.sections} sections and a {d.compliance_rows}-row compliance matrix with page references.</div>
            <div className="num text-[22px] font-bold mt-3">{money(d.price, d.currency)}</div>
            <div className="text-[12px] text-ink-muted">{d.scenario} pricing scenario</div>
            {edited && <button className="btn-ember w-full mt-4" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>{rebuild.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Update document with edits</button>}
            <ProposalDownload dealId={deal.id} />
            <button className="btn-outline w-full mt-2" onClick={() => download(`/deals/${deal.id}/download/requirements`, "requirements.xlsx").catch((e) => toast("error", e.message))}><Download className="h-4 w-4" /> Compliance matrix .xlsx</button>
            <button className="btn-ghost w-full mt-2" disabled={regen.isPending} onClick={() => regen.mutate()} title="Re-drafts every answer except the ones your team wrote"><RefreshCw className="h-4 w-4" /> Re-draft with AI</button>
          </div>
          <div className="card p-5 text-[13px]">
            <div className="font-bold text-[14px] mb-2">Where the answers came from</div>
            <ShareBar parts={[["library", "#0C3D55"], ["human", "#F5833A"], ["ai", "#1A82AE"], ["rules", "#9FC6D9"]].map(([k, c]) => ({ label: SRC[k][0], value: counts[k] || 0, color: c }))} />
            <div className="text-[12px] text-ink-muted mt-3">Approving this stage adds these answers to your library, so the next similar RFP starts from them.</div>
          </div>
        </aside>
      </div>
      <StoryVideo dealId={deal.id} />
      <div className="card">
        <div className="px-4 py-2.5 border-b border-line flex flex-wrap gap-2 items-center">
          <div className="font-bold mr-2">Answers in the compliance matrix</div>
          {[["all", "All"], ["library", "Library"], ["ai", "AI draft"], ["human", "Team-written"]].map(([k, l]) => (
            <button key={k} onClick={() => setFilter(k)} className={clsx("btn h-8 px-3", filter === k ? "bg-brand-900 text-white" : "text-ink-soft hover:bg-line-soft")}>{l} <span className="num opacity-80">{k === "all" ? reqs.filter((r) => r.response).length : counts[k] || 0}</span></button>
          ))}
          <div className="flex-1" /><span className="text-[12px] text-ink-muted">Edit any answer; RevenueForge learns your team's style from rewrites.</span>
        </div>
        <ul className="divide-y divide-line-soft max-h-[70vh] overflow-auto scroll-thin">
          {answers.map((r) => <ResponseRow key={r.id} dealId={deal.id} r={r} onSaved={() => { setEdited(true); qc.invalidateQueries({ queryKey: ["reqs", deal.id] }); }} />)}
          {answers.length === 0 && <Empty title="No answers in this view" />}
        </ul>
      </div>
    </div>
  );
}

// =============================================================== 8. handoff
export function HandoffStage({ deal }: P) {
  const toast = useToast();
  const { data: st } = useStage(deal.id, "handoff");
  if (!st) return <PageLoader />;
  const h = st.data;
  const Section = ({ title, children }: any) => <div className="card p-5"><div className="font-bold mb-3">{title}</div>{children}</div>;
  return (
    <div className="space-y-4">
      <div className="card p-5 flex flex-wrap items-center gap-4">
        <div className="flex-1 min-w-[260px] text-[14.5px] text-ink-soft">{h.summary}</div>
        <button className="btn-primary" onClick={() => download(`/deals/${deal.id}/download/handoff`, "handoff.docx").catch((e) => toast("error", e.message))}><Download className="h-4 w-4" /> Download handoff pack</button>
      </div>
      <div className="grid lg:grid-cols-2 gap-4">
        <Section title="Scope by workstream">
          <table className="w-full"><tbody>{h.scope.map((s: any) => <tr key={s.workstream}><td className="py-1.5 text-[13.5px]">{s.workstream}</td><td className="py-1.5 text-right num text-[13px] text-ink-muted">{s.requirements} reqs</td><td className="py-1.5 text-right num text-[13px] font-semibold w-20">{Math.round(s.effort_days)} d</td></tr>)}</tbody></table>
        </Section>
        <Section title="Open items before mobilisation">
          {h.open_items.length ? <ul className="space-y-1.5 text-[13.5px] text-ink-soft list-disc pl-5">{h.open_items.map((o: string) => <li key={o}>{o}</li>)}</ul> : <div className="text-sm text-ink-muted">None.</div>}
        </Section>
        <Section title="Team">
          <div className="space-y-1.5">{h.team.map((t: any, i: number) => <div key={i} className="flex justify-between gap-3 text-[13.5px]"><span>{t.role} <span className="text-ink-muted">· {t.location}</span></span><span className="num text-ink-muted text-right">{t.people.join(", ")}{t.unfilled ? ` +${t.unfilled} hire` : ""}</span></div>)}</div>
        </Section>
        <Section title="Plan & milestones">
          <div className="space-y-1.5 text-[13.5px]">{h.milestones.map((m: any) => <div key={m.name} className="flex justify-between"><span>{m.name}</span><span className="num text-ink-muted">{m.pct}%</span></div>)}</div>
        </Section>
        {h.out_of_scope.length > 0 && <Section title="Out of scope"><ul className="list-disc pl-5 text-[13.5px] text-ink-soft space-y-1">{h.out_of_scope.map((o: string) => <li key={o}>{o}</li>)}</ul></Section>}
        {h.slas.length > 0 && <Section title="Service levels committed"><ul className="text-[13px] text-ink-soft space-y-1">{h.slas.map((o: string) => <li key={o}>{o}</li>)}</ul></Section>}
        <Section title="Top risks">
          <ul className="space-y-2">{h.risks.slice(0, 8).map((r: any) => <li key={r.code} className="text-[13px]"><div className="flex gap-2 items-center"><RiskChip risk={r.level} /><span className="num text-ink-muted text-[12px]">{r.ref || r.code}</span></div><div className="text-ink-soft mt-0.5 line-clamp-2">{r.risk}</div></li>)}</ul>
        </Section>
        <Section title="First 30 days"><ol className="list-decimal pl-5 text-[13.5px] text-ink-soft space-y-1">{h.first_30_days.map((o: string) => <li key={o}>{o}</li>)}</ol></Section>
      </div>
    </div>
  );
}
