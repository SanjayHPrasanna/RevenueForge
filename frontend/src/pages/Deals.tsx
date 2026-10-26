import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, EyeOff, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Dropzone, Empty, Meter, Modal, PageLoader, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { ago, ENGAGEMENT, money } from "../lib/format";
import { DealStatus } from "./Dashboard";

function NewDeal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [det, setDet] = useState<any>(null);
  const [detecting, setDetecting] = useState(false);
  const { data: company } = useQuery({ queryKey: ["company"], queryFn: () => api.get("/company") });
  const [f, setF] = useState({ name: "", client_name: "", client_aliases: "", client_alias: "", confidential: true, engagement_type: "" });
  useEffect(() => {
    if (!open) {
      setFile(null);
      setDet(null);
    }
  }, [open]);
  const pick = async (fl: File) => {
    setFile(fl);
    setDetecting(true);
    try {
      const fd = new FormData();
      fd.append("file", fl);
      const d = await api.upload("/deals/detect", fd);
      setDet(d);
      setF((x) => ({ ...x, name: d.title || "", client_name: d.client_name || "", client_aliases: (d.client_aliases || []).join(", "), engagement_type: d.engagement_type || "" }));
    } catch (e: any) {
      toast("error", e.message);
      setFile(null);
    } finally {
      setDetecting(false);
    }
  };
  const create = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("file", file!);
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
      {company?.llm?.enabled && !company.llm.paid && (
        <div className="mb-4 rounded-md border border-ember-100 bg-ember-50 px-3.5 py-2.5 text-[12.5px] text-ember-600">
          <b>Free Gemini tier:</b> Google may use content sent on the free tier to improve its products, and reviewers may read it. Use sample or non-confidential documents, or switch to a paid key (set <code>LLM_PAID=true</code>) for client RFPs.
        </div>
      )}
      {!file || detecting ? (
        <Dropzone accept=".pdf,.docx,.txt" onFile={pick} busy={detecting} label="Drop the RFP, RFI, RFQ or SOW here or browse" hint="PDF or Word, up to 40 MB" />
      ) : (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <div className="rounded-md bg-paper border border-line px-3 py-2 text-[13px] flex flex-wrap gap-x-4 gap-y-1">
            <span className="font-semibold truncate max-w-full">{file.name}</span>
            {det && <span className="text-ink-muted">{det.doc_type} · {det.pages} pages · {det.industry}{det.region ? ` · ${det.region}` : ""}{det.currency ? ` · ${det.currency}` : ""}</span>}
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
              <input type="checkbox" className="mt-1 h-4 w-4 accent-[#118AC3]" checked={f.confidential} onChange={set("confidential")} />
              <span>
                <span className="font-semibold text-sm flex items-center gap-1.5"><EyeOff className="h-4 w-4 text-brand-600" /> Keep the client confidential</span>
                <span className="block text-[12.5px] text-ink-muted mt-0.5">The client's names are replaced with an alias on every screen, in AI prompts and in generated documents.</span>
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
            <button className="btn-primary" disabled={create.isPending}>{create.isPending && <Spinner />} Analyse RFP</button>
            <button type="button" className="btn-ghost" onClick={() => setFile(null)}>Choose another file</button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export default function Deals() {
  const [sp, setSp] = useSearchParams();
  const { data, isLoading } = useQuery({ queryKey: ["deals"], queryFn: () => api.get("/deals"), refetchInterval: 5000 });
  const open = sp.get("new") === "1";
  return (
    <div className="px-4 lg:px-8 py-6 max-w-[1400px]">
      <div className="flex items-center gap-3 mb-5">
        <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Deals</h1>
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
                  <td className="td max-w-[340px]">
                    <Link to={`/app/deals/${d.id}`} className="font-semibold hover:text-brand-700 line-clamp-1">{d.name}</Link>
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
