import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, EyeOff, FileText, Plus, Star, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Dropzone, Empty, Meter, Modal, PageLoader, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { ago, ENGAGEMENT, money } from "../lib/format";
import { DealStatus } from "./Dashboard";
import { OwnerTag } from "../components/review";
import { prefetchDeal } from "../lib/prefetch";

function NewDeal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);  // the first one is the main RFP; the rest are read with it
  const more = useRef<HTMLInputElement>(null);
  const file = files[0] || null;
  const [det, setDet] = useState<any>(null);
  const [detecting, setDetecting] = useState(false);
  const { data: company } = useQuery({ queryKey: ["company"], queryFn: () => api.get("/company") });
  const [f, setF] = useState({ name: "", client_name: "", client_aliases: "", client_alias: "", confidential: true, engagement_type: "" });
  useEffect(() => {
    if (!open) {
      setFiles([]);
      setDet(null);
    }
  }, [open]);
  const OK = /\.(pdf|docx|txt|xlsx|xlsm|csv|pptx|md)$/i;
  const addFiles = (list: File[]) => {
    const good = list.filter((x) => OK.test(x.name));
    if (good.length < list.length) toast("error", "Some files were skipped: use PDF, Word, Excel, CSV, PowerPoint or text.");
    const merged = [...files, ...good.filter((g) => !files.some((x) => x.name === g.name && x.size === g.size))].slice(0, 10);
    if (files.length + good.length > 10) toast("error", "Up to 10 files per deal.");
    if (!merged.length) return;
    setFiles(merged);
    if (!files.length) {
      // read the details (title, client, industry) from the main tender document: the first PDF or Word file
      const main = merged.find((x) => /\.(pdf|docx)$/i.test(x.name)) || merged[0];
      const ordered = [main, ...merged.filter((x) => x !== main)];
      setFiles(ordered);
      detect(main);
    }
  };
  const makeMain = (i: number) => { const next = [files[i], ...files.filter((_, j) => j !== i)]; setFiles(next); detect(next[0]); };
  const removeAt = (i: number) => { const next = files.filter((_, j) => j !== i); setFiles(next); if (i === 0 && next.length) detect(next[0]); if (!next.length) setDet(null); };
  const detect = async (fl: File) => {
    setDetecting(true);
    try {
      const fd = new FormData();
      fd.append("file", fl);
      const d = await api.upload("/deals/detect", fd);
      setDet(d);
      setF((x) => ({ ...x, name: d.title || "", client_name: d.client_name || "", client_aliases: (d.client_aliases || []).join(", "), engagement_type: d.engagement_type || "" }));
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setDetecting(false);
    }
  };
  const create = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      files.forEach((x) => fd.append("files", x));
      Object.entries(f).forEach(([k, v]) => fd.append(k, String(v)));
      return api.upload("/deals", fd);
    },
    onSuccess: (d) => {
      qc.invalidateQueries();
      onClose();
      nav(`/app/deals/${d.id}`);
    },
    onError: (e: any) => toast("error", e.message),
  });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <Modal open={open} onClose={onClose} title="New deal" wide>
      {!file || (detecting && !det) ? (
        <Dropzone accept=".pdf,.docx,.txt,.xlsx,.xlsm,.csv,.pptx,.md" onFiles={addFiles} busy={detecting}
          label="Upload one or more tender files here: RFP, RFQ, RFI, SOW, annexures, addenda or pricing sheets"
          hint="Drop them together or browse. PDF, Word, Excel, CSV, PowerPoint or text · up to 10 files, 40 MB each" />
      ) : (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <div className="rounded-md bg-paper border border-line">
            <div className="px-3 py-2 text-[12.5px] text-ink-muted border-b border-line-soft flex items-center gap-2">
              <span className="flex-1">{files.length === 1 ? "1 file" : `${files.length} files, read together as one tender`}
                {det && ` · main: ${det.doc_type} · ${det.pages} pages · ${det.industry}${det.region ? ` · ${det.region}` : ""}${det.currency ? ` · ${det.currency}` : ""}`}</span>
              {detecting && <Spinner />}
            </div>
            <ul className="divide-y divide-line-soft">
              {files.map((x, i) => (
                <li key={x.name + x.size} className="px-3 py-1.5 flex items-center gap-2 text-[13px]">
                  <FileText className="h-4 w-4 text-ink-faint shrink-0" />
                  <span className="truncate flex-1 min-w-0" title={x.name}>{x.name}</span>
                  <span className="text-[11.5px] text-ink-faint num">{x.size >= 1048576 ? `${(x.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(x.size / 1024))} KB`}</span>
                  {i === 0 ? <span className="chip bg-brand-500/10 text-brand-700 text-[11px]">Main RFP</span>
                    : <button type="button" className="btn-ghost h-7 px-2 text-[12px]" onClick={() => makeMain(i)} title="Read the deal's details from this file"><Star className="h-3.5 w-3.5" /> Make main</button>}
                  <button type="button" className="btn-ghost h-7 w-7 p-0" onClick={() => removeAt(i)} aria-label={`Remove ${x.name}`}><X className="h-3.5 w-3.5" /></button>
                </li>
              ))}
            </ul>
            <div className="px-3 py-2 border-t border-line-soft">
              <input ref={more} type="file" multiple hidden accept=".pdf,.docx,.txt,.xlsx,.xlsm,.csv,.pptx,.md"
                onChange={(e) => { addFiles(Array.from(e.target.files || [])); e.target.value = ""; }} />
              <button type="button" className="btn-ghost h-8 text-[13px]" disabled={files.length >= 10} onClick={() => more.current?.click()}><Plus className="h-3.5 w-3.5" /> Add more files (RFQ, annexures, addenda…)</button>
            </div>
          </div>
          <div>
            <label className="label">Deal name</label>
            <input className="input" value={f.name} onChange={set("name")} required />
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label className="label">Client name</label>
              <input className="input" value={f.client_name} onChange={set("client_name")} placeholder="Issuing organisation" />
            </div>
            <div>
              <label className="label">Other names to mask</label>
              <input className="input" value={f.client_aliases} onChange={set("client_aliases")} placeholder="Acronyms, short names (comma separated)" />
            </div>
          </div>
          <div className="rounded-md border border-line p-3.5">
            <label className="flex items-start gap-3 cursor-pointer">
              <input type="checkbox" className="mt-1 h-4 w-4 accent-[#118AC3]" checked={f.confidential} onChange={set("confidential")}
                aria-label="Keep the client confidential" aria-describedby="conf-help" />
              <span>
                <span className="font-semibold text-sm flex items-center gap-1.5"><EyeOff className="h-4 w-4 text-brand-600" /> Keep the client confidential</span>
                <span id="conf-help" className="block text-[12.5px] text-ink-muted mt-0.5">The client's names are replaced with an alias on every screen, in AI prompts and in generated documents.</span>
              </span>
            </label>
            {f.confidential && (
              <div className="mt-3 sm:pl-7">
                <label className="label">Alias shown instead</label>
                <input className="input max-w-xs" value={f.client_alias} onChange={set("client_alias")} placeholder="e.g. Client A" />
              </div>
            )}
          </div>
          <div>
            <label className="label">Engagement model</label>
            <select className="input max-w-xs" value={f.engagement_type} onChange={set("engagement_type")}>
              <option value="">Detect from the document</option>
              {Object.entries(ENGAGEMENT).map(([k, v]) => <option key={k} value={k}>{v}{det?.engagement_type === k ? " (detected)" : ""}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-3 pt-2">
            <button className="btn-primary" disabled={create.isPending || detecting}>{create.isPending && <Spinner />} Analyse {files.length > 1 ? `${files.length} files` : "RFP"}</button>
            <button type="button" className="btn-ghost" onClick={() => { setFiles([]); setDet(null); }}>Start over</button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export default function Deals() {
  const [sp, setSp] = useSearchParams();
  const qc = useQueryClient();
  // Refresh every few seconds only while a deal is being worked on; otherwise once a minute.
  const { data, isLoading } = useQuery({ queryKey: ["deals"], queryFn: () => api.get("/deals"),
    refetchInterval: (q) => (((q.state.data as any[]) || []).some((d) => d.status === "processing") ? 3000 : 60000) });
  const open = sp.get("new") === "1";
  return (
    <div className="px-4 lg:px-8 py-6 max-w-[1400px]">
      <div className="flex items-center gap-3 mb-5">
        <h1 className="font-display font-semibold text-[26px] md:text-[30px] leading-[1.05] tracking-[-0.025em] text-brand-950">Deals</h1>
        <div className="flex-1" />
        <button className="btn-primary" onClick={() => setSp({ new: "1" })}><Plus className="h-4 w-4" /> New deal</button>
      </div>
      {isLoading ? <PageLoader /> : !data?.length ? (
        <div className="card">
          <Empty icon={<Briefcase className="h-8 w-8" />} title="Upload your first RFP" action={<button className="btn-primary" onClick={() => setSp({ new: "1" })}>New deal</button>}>
            RevenueForge extracts every requirement, matches it to your capabilities and drafts the full deal package.
          </Empty>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[860px]">
            <thead>
              <tr>
                <th className="th">Deal</th><th className="th">Type</th><th className="th">Status</th><th className="th text-right">Requirements</th>
                <th className="th">Coverage</th><th className="th text-right">Value</th><th className="th">Due</th><th className="th">Created</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d: any) => (
                <tr key={d.id} className="hover:bg-paper">
                  <td className="td max-w-[420px]">
                    <div className="flex items-center gap-2 min-w-0"><Link to={`/app/deals/${d.id}`} onMouseEnter={() => prefetchDeal(qc, d.id)} className="font-semibold hover:text-brand-700 line-clamp-1 min-w-0">{d.name}</Link><OwnerTag owner={d.owner} className="shrink-0" />{d.open_notes > 0 && <span className="chip bg-ember-100 text-ember-600 shrink-0" title="Open review notes">{d.open_notes} to fix</span>}</div>
                    <div className="text-[12px] text-ink-muted flex items-center gap-1">
                      {d.confidential && <EyeOff className="h-3 w-3" />} {d.client} · {d.industry || "—"}{d.region ? ` · ${d.region}` : ""}
                    </div>
                  </td>
                  <td className="td text-[13px]">{d.doc_type} · {ENGAGEMENT[d.engagement_type] || "—"}</td>
                  <td className="td">
                    <DealStatus s={d.status} />
                    {d.status === "processing" && <div className="text-[11.5px] text-ink-muted mt-1">{d.progress?.message}</div>}
                  </td>
                  <td className="td text-right num">{d.requirement_count || "—"}</td>
                  <td className="td w-[150px]">
                    {d.coverage_pct != null ? (<><div className="num text-[12px] font-semibold">{d.coverage_pct}%</div><Meter value={d.coverage_pct} className="mt-1" /></>) : "—"}
                  </td>
                  <td className="td text-right num font-semibold">{d.value ? money(d.value, d.value_currency) : "—"}</td>
                  <td className="td text-[13px]">{d.due_date || "—"}</td>
                  <td className="td text-[13px] text-ink-muted">{ago(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <NewDeal open={open} onClose={() => setSp({})} />
    </div>
  );
}
