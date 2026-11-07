import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Building2, CheckCircle2, FileSearch, Info, MapPin, Send, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Dropzone, Empty, Modal, PageLoader, Spinner, StatStrip, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ago } from "../lib/format";

const REGIONS = ["", "Europe", "United Kingdom", "North America", "Latin America & Caribbean", "Middle East & North Africa", "Sub-Saharan Africa",
  "South Asia", "East Asia & Pacific", "Central Asia & Caucasus"];
const INVITE_STYLE: Record<string, string> = { invited: "bg-brand-50 text-brand-700", accepted: "bg-[#E4F1F7] text-fit-strong-ink", declined: "bg-line-soft text-ink-muted" };

function NewRequest({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [f, setF] = useState({ title: "", region: "", industry: "", due_date: "" });
  const go = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("file", file!);
      Object.entries(f).forEach(([k, v]) => fd.append(k, v));
      return api.upload<any>("/buyer/requests", fd);
    },
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["buyer-requests"] }); onClose(); nav(`/app/buyer/${r.id}`); },
    onError: (e: any) => toast("error", e.message),
  });
  return (
    <Modal open={open} onClose={onClose} title="Find suppliers for an RFP" wide>
      <div className="space-y-4 text-[13.5px]">
        <p className="text-ink-muted">Upload your RFP or statement of work. RevenueForge reads its requirements and ranks the suppliers in the network by how well their proven work covers them.</p>
        <Dropzone accept=".pdf,.docx,.doc,.txt,.xlsx" onFile={setFile} hint={file ? file.name : "PDF, Word, Excel or text"} />
        <div className="grid sm:grid-cols-2 gap-3">
          <label><span className="label">Title (optional)</span><input className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Read from the document if empty" /></label>
          <label><span className="label">Where the work is</span>
            <select className="input" value={f.region} onChange={(e) => setF({ ...f, region: e.target.value })}>{REGIONS.map((r) => <option key={r} value={r}>{r || "Any region"}</option>)}</select></label>
          <label><span className="label">Industry (optional)</span><input className="input" value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })} placeholder="e.g. Transportation" /></label>
          <label><span className="label">Response deadline (optional)</span><input className="input" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} placeholder="e.g. 30 November 2026" /></label>
        </div>
        <button className="btn-primary" disabled={!file || go.isPending} onClick={() => go.mutate()}>{go.isPending && <Spinner />} Read the RFP and find suppliers</button>
      </div>
    </Modal>
  );
}

export function BuyerRequests() {
  const [open, setOpen] = useState(false);
  const canEdit = useAuth().user?.role !== "viewer";
  const { data } = useQuery({ queryKey: ["buyer-requests"], queryFn: () => api.get<any[]>("/buyer/requests") });
  if (!data) return <PageLoader />;
  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1300px]">
      <div className="flex flex-wrap items-end gap-4 mb-6">
        <div className="flex-1 min-w-[280px]">
          <div className="eyebrow mb-1.5">Supplier network</div>
          <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Your requests</h1>
          <p className="text-ink-muted text-[14px] mt-1">Upload an RFP, see which suppliers have proven they can deliver it, and invite the right ones to bid.</p>
        </div>
        {canEdit
          ? <button className="btn-primary" onClick={() => setOpen(true)}><FileSearch className="h-4 w-4" /> Find suppliers for an RFP</button>
          : <span className="text-[12.5px] text-ink-muted">Viewers can look at requests but not create them.</span>}
      </div>
      <div className="card overflow-x-auto">
        {data.length === 0 ? (
          <Empty icon={<FileSearch className="h-8 w-8" />} title="No requests yet" action={<button className="btn-primary" onClick={() => setOpen(true)}>Upload an RFP</button>}>
            Your RFP is read once to find its requirements. Suppliers only see it after you invite them.
          </Empty>
        ) : (
          <table className="w-full min-w-[760px]">
            <thead><tr><th className="th">Request</th><th className="th text-right">Requirements</th><th className="th text-right">Invited</th><th className="th text-right">Accepted</th><th className="th">Created</th></tr></thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id} className="hover:bg-paper">
                  <td className="td"><Link to={`/app/buyer/${r.id}`} className="font-semibold hover:text-brand-700">{r.title}</Link>
                    <div className="text-[12px] text-ink-muted">{[r.region, r.industry, r.due_date && `Due ${r.due_date}`].filter(Boolean).join(" · ")}</div></td>
                  <td className="td text-right num">{r.requirements} <span className="text-ink-faint text-[12px]">({r.mandatory} mandatory)</span></td>
                  <td className="td text-right num">{r.invited}</td>
                  <td className="td text-right num">{r.accepted}</td>
                  <td className="td text-[13px] text-ink-muted">{ago(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <NewRequest open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function VendorProfile({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data: v } = useQuery({ queryKey: ["vendor", id], queryFn: () => api.get<any>(`/buyer/vendors/${id}`), enabled: !!id });
  return (
    <Modal open={!!id} onClose={onClose} title={v?.name || "Supplier"} xl>
      {!v ? <PageLoader /> : (
        <div className="space-y-5 text-[13.5px]">
          {v.demo && <div className="rounded-lg border border-ember-100 bg-ember-50 px-3 py-2 text-ember-600 text-[12.5px]">Fictional demo supplier: this company and its work are invented to demonstrate the network.</div>}
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-ink-muted">
            {v.headquarters && <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{v.headquarters}</span>}
            {v.headcount > 0 && <span className="inline-flex items-center gap-1"><Users className="h-3.5 w-3.5" />{v.headcount} people</span>}
            {v.regions?.length > 0 && <span>Serves: {v.regions.join(", ")}</span>}
          </div>
          {v.summary && <p className="text-ink-soft leading-relaxed">{v.summary}</p>}
          <div className="grid lg:grid-cols-2 gap-5">
            <section><div className="font-semibold mb-2">Capabilities</div>
              <ul className="space-y-2">{v.capabilities.map((c: any) => <li key={c.name}><div className="font-medium">{c.name}</div><div className="text-[12.5px] text-ink-muted">{c.description}</div>
                {c.technologies?.length > 0 && <div className="text-[12px] text-brand-700 mt-0.5">{c.technologies.join(", ")}</div>}</li>)}</ul></section>
            <section><div className="font-semibold mb-2">Case studies</div>
              <ul className="space-y-2">{v.case_studies.map((c: any) => <li key={c.title}><div className="font-medium">{c.title}</div>
                <div className="text-[12px] text-ink-muted">{[c.industry, c.region, c.year].filter(Boolean).join(" · ")}</div>
                <div className="text-[12.5px] text-ink-soft">{c.summary}</div>
                {c.outcomes?.length > 0 && <div className="text-[12px] text-ok mt-0.5">{c.outcomes.join(" · ")}</div>}</li>)}</ul></section>
          </div>
          <div className="grid lg:grid-cols-2 gap-5">
            <section><div className="font-semibold mb-2">Certificates and partnerships</div>
              {v.certifications.length ? <ul className="space-y-1">{v.certifications.map((c: any) => <li key={c.name}>{c.name} <span className="text-ink-muted text-[12px]">· {c.kind === "partner" ? "Partnership" : "Company certificate"}{c.issuer ? `, ${c.issuer}` : ""}</span></li>)}</ul>
                : <div className="text-ink-muted">None listed.</div>}</section>
            <section><div className="font-semibold mb-2">Depth of skills</div>
              {v.skills.length ? <div className="flex flex-wrap gap-1.5">{v.skills.map((s: any) => <span key={s.technology} className="chip bg-paper border border-line text-ink-soft">{s.technology} · {s.people}</span>)}</div>
                : <div className="text-ink-muted">Not shared.</div>}
              <div className="text-[12px] text-ink-muted mt-2">Number of people at an experienced level. Names, rates and clients are never shared.</div></section>
          </div>
        </div>
      )}
    </Modal>
  );
}

export function BuyerRequest() {
  const { id } = useParams();
  const toast = useToast();
  const nav = useNavigate();
  const qc = useQueryClient();
  const canEdit = useAuth().user?.role !== "viewer";
  const [picked, setPicked] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const [profile, setProfile] = useState<string | null>(null);
  const [showReqs, setShowReqs] = useState(false);
  const { data: r } = useQuery({ queryKey: ["buyer-request", id], queryFn: () => api.get<any>(`/buyer/requests/${id}`) });
  const { data: sl, isLoading } = useQuery({ queryKey: ["shortlist", id], queryFn: () => api.get<any>(`/buyer/requests/${id}/shortlist`) });
  const invite = useMutation({
    mutationFn: () => api.post<any>(`/buyer/requests/${id}/invite`, { vendor_ids: picked, message: msg }),
    onSuccess: (x) => { toast("ok", `${x.invited} supplier${x.invited === 1 ? "" : "s"} invited.`); setPicked([]); qc.invalidateQueries({ queryKey: ["buyer-request", id] }); qc.invalidateQueries({ queryKey: ["shortlist", id] }); },
    onError: (e: any) => toast("error", e.message),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/buyer/requests/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["buyer-requests"] }); nav("/app/buyer"); },
    onError: (e: any) => toast("error", e.message),
  });
  if (!r) return <PageLoader />;
  const toggle = (v: string) => setPicked(picked.includes(v) ? picked.filter((x) => x !== v) : [...picked, v]);
  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1400px] space-y-5">
      <div>
        <Link to="/app/buyer" className="text-[13px] text-ink-muted hover:text-brand-700 inline-flex items-center gap-1"><ArrowLeft className="h-3.5 w-3.5" /> Requests</Link>
        <div className="flex flex-wrap items-end gap-3 mt-2">
          <h1 className="flex-1 min-w-[300px] font-display text-[32px] leading-tight text-brand-950">{r.title}</h1>
          {canEdit && <button className="btn-ghost" onClick={() => confirm("Delete this request? Invited suppliers will no longer see it.") && del.mutate()}><Trash2 className="h-4 w-4" /> Delete</button>}
        </div>
        <div className="text-[13px] text-ink-muted mt-1">{[r.filename, r.region || "Any region", r.industry, r.due_date && `Due ${r.due_date}`].filter(Boolean).join(" · ")}</div>
      </div>
      <StatStrip items={[
        { label: "Requirements found", value: r.requirements, sub: `${r.mandatory} mandatory` },
        { label: "Suppliers compared", value: sl ? sl.listed : "…", sub: "Every listed supplier" },
        { label: "Invited", value: r.invited, sub: `${r.accepted} accepted, ${r.declined} declined` },
      ]} />
      <section className="card">
        <button className="w-full flex items-center justify-between px-5 py-3.5 text-left" onClick={() => setShowReqs(!showReqs)} aria-expanded={showReqs}>
          <span className="font-semibold">Requirements read from your RFP</span>
          <span className="text-[12.5px] text-ink-muted">{Object.entries(r.by_category || {}).map(([k, v]) => `${v} ${String(k).toLowerCase()}`).join(", ")} · {showReqs ? "Hide" : "Show"}</span>
        </button>
        {showReqs && (
          <ul className="border-t border-line-soft max-h-[360px] overflow-auto scroll-thin divide-y divide-line-soft">
            {r.sample.map((x: any, i: number) => (
              <li key={i} className="px-5 py-2 text-[13px] flex gap-3"><span className="w-16 shrink-0 num text-ink-muted">{x.ref || i + 1}</span><span className="flex-1">{x.text}</span>
                <span className="text-[12px] text-ink-muted w-28 shrink-0">{x.category}{x.priority === "Mandatory" ? " · M" : ""}</span></li>
            ))}
          </ul>
        )}
      </section>
      <section className="card overflow-x-auto">
        <div className="px-5 py-4 border-b border-line flex flex-wrap items-start gap-3">
          <div className="flex-1 min-w-[300px]">
            <div className="font-bold">Suppliers who can deliver this</div>
            <div className="text-[12.5px] text-ink-muted mt-0.5 flex gap-1.5"><Info className="h-3.5 w-3.5 mt-0.5 shrink-0 text-brand-600" />{sl?.method}</div>
          </div>
        </div>
        {isLoading ? <PageLoader label="Comparing every listed supplier with your requirements" /> : !sl?.vendors?.length ? (
          <Empty icon={<Building2 className="h-8 w-8" />} title="No suppliers are listed yet">Suppliers appear here once they choose to list their company in the network.</Empty>
        ) : (
          <table className="w-full min-w-[980px]">
            <thead><tr><th className="th w-10"><span className="sr-only">Select</span></th><th className="th w-[110px]">Coverage</th><th className="th">Supplier</th><th className="th">Proven by</th><th className="th">Watch out for</th><th className="th">Invitation</th></tr></thead>
            <tbody>
              {sl.vendors.map((v: any) => (
                <tr key={v.vendor_id} className={clsx(picked.includes(v.vendor_id) && "bg-brand-50/60")}>
                  <td className="td align-top">{canEdit && !v.invite_status && <input type="checkbox" className="h-4 w-4 mt-1 accent-[#118AC3]" aria-label={`Select ${v.name}`}
                    checked={picked.includes(v.vendor_id)} onChange={() => toggle(v.vendor_id)} />}</td>
                  <td className="td align-top"><div className="num font-bold text-[18px]">{v.score}%</div>
                    <div className="text-[11.5px] text-ink-muted">{v.coverage.strong || 0} strong · {v.coverage.partial || 0} partial · {v.coverage.gap || 0} gaps</div></td>
                  <td className="td align-top">
                    <button className="font-semibold text-left hover:text-brand-700" onClick={() => setProfile(v.vendor_id)}>{v.name}</button>
                    {v.demo && <span className="chip ml-2 bg-ember-50 text-ember-600 text-[10.5px]">Fictional demo supplier</span>}
                    <div className="text-[12px] text-ink-muted">{v.headquarters}{v.regions?.length ? ` · serves ${v.regions.slice(0, 3).join(", ")}` : ""}</div>
                  </td>
                  <td className="td align-top text-[12.5px] max-w-[300px]">{v.strengths.slice(0, 3).map((s: any) => <div key={s.name} className="truncate"><span className="text-ink-muted">{s.type}:</span> {s.name} <span className="text-ink-faint">({s.requirements})</span></div>)}
                    {!v.strengths.length && <span className="text-ink-faint">Nothing close in their library</span>}</td>
                  <td className="td align-top text-[12.5px] text-ink-soft max-w-[320px]">{v.notes.map((n: string) => <div key={n}>{n}</div>)}</td>
                  <td className="td align-top">{v.invite_status ? <span className={clsx("chip capitalize", INVITE_STYLE[v.invite_status])}>{v.invite_status}</span> : <span className="text-ink-faint text-[12px]">Not invited</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {picked.length > 0 && (
          <div className="sticky bottom-0 border-t border-line bg-white/95 backdrop-blur px-5 py-3 flex flex-wrap items-center gap-3">
            <span className="text-[13px] font-semibold">{picked.length} selected</span>
            <input className="input h-9 flex-1 min-w-[280px]" placeholder="Message to the suppliers (optional), e.g. clarification deadline" value={msg} onChange={(e) => setMsg(e.target.value)} aria-label="Message to suppliers" />
            <button className="btn-primary" disabled={invite.isPending} onClick={() => invite.mutate()}>{invite.isPending ? <Spinner /> : <Send className="h-4 w-4" />} Invite to bid</button>
          </div>
        )}
      </section>
      {r.invites?.length > 0 && (
        <section className="card p-5">
          <div className="font-bold mb-3">Invitations</div>
          <ul className="divide-y divide-line-soft text-[13.5px]">
            {r.invites.map((i: any) => (
              <li key={i.id} className="py-2.5 flex items-center gap-3">
                {i.status === "accepted" ? <CheckCircle2 className="h-4 w-4 text-ok" /> : <Send className="h-4 w-4 text-ink-faint" />}
                <span className="flex-1">{i.vendor.name}{i.vendor.demo && <span className="text-ember-600 text-[12px]"> (fictional demo supplier: it can't respond)</span>}</span>
                <span className="text-[12px] text-ink-muted">{i.fit}% coverage when invited · {ago(i.created_at)}</span>
                <span className={clsx("chip capitalize", INVITE_STYLE[i.status])}>{i.status}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <VendorProfile id={profile} onClose={() => setProfile(null)} />
    </div>
  );
}
