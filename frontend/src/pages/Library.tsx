import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, FileText, FolderUp, Search, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { NavLink, useParams } from "react-router-dom";
import FolderImport from "../components/FolderImport";
import GoogleDriveImport from "../components/GoogleDriveImport";
import UploadReview, { KIND_INFO, TemplateUpload } from "../components/UploadReview";
import { Empty, Modal, PageLoader, useToast } from "../components/ui";
import { api, download } from "../lib/api";
import { ago } from "../lib/format";

const TABS = [
  { key: "capabilities", label: "Capabilities" },
  { key: "skills", label: "People & skills" },
  { key: "certifications", label: "Certifications" },
  { key: "rates", label: "Rate card" },
  { key: "case_studies", label: "Case studies" },
  { key: "accelerators", label: "Accelerators" },
  { key: "template", label: "Proposal template" },
];

const COLS: Record<string, { key: string; label: string; render?: (r: any) => any; cls?: string }[]> = {
  capabilities: [
    { key: "name", label: "Capability", render: (r) => <><div className="font-semibold">{r.name}</div><div className="text-[12.5px] text-ink-muted line-clamp-2 max-w-xl">{r.description}</div></> },
    { key: "service_line", label: "Service line" },
    { key: "technologies", label: "Technologies", render: (r) => <Tags v={r.technologies} /> },
    { key: "industries", label: "Industries", render: (r) => (r.industries || []).join(", ") },
  ],
  skills: [
    { key: "code", label: "Employee", render: (r) => <span className="num font-semibold">{r.name || r.code}</span> },
    { key: "role", label: "Role", render: (r) => <>{r.role}<div className="text-[12px] text-ink-muted">{r.level}{r.years ? ` · ${r.years} yrs` : ""}</div></> },
    { key: "location", label: "Location" },
    { key: "skills", label: "Skills", render: (r) => <Tags v={(r.skills || []).sort((a: any, b: any) => b.level - a.level).map((s: any) => `${s.name} ${s.level}`)} max={6} /> },
    { key: "availability", label: "Available", cls: "text-right num", render: (r) => `${Math.round(r.availability)}%` },
  ],
  certifications: [
    { key: "name", label: "Certification", render: (r) => <span className="font-semibold">{r.name}</span> },
    { key: "kind", label: "Type", render: (r) => <span className="capitalize">{r.kind}</span> },
    { key: "issuer", label: "Issuer" },
    { key: "holders", label: "Holders", cls: "text-right num", render: (r) => r.holders || "—" },
    { key: "valid_until", label: "Valid until" },
  ],
  rates: [
    { key: "role", label: "Role", render: (r) => <span className="font-semibold">{r.role}</span> },
    { key: "level", label: "Level" },
    { key: "location", label: "Location" },
    { key: "day_rate", label: "Day rate", cls: "text-right num", render: (r) => `${r.currency} ${Math.round(r.day_rate).toLocaleString()}` },
    { key: "day_cost", label: "Day cost", cls: "text-right num", render: (r) => `${r.currency} ${Math.round(r.day_cost).toLocaleString()}` },
    { key: "m", label: "Margin", cls: "text-right num", render: (r) => (r.day_rate ? `${Math.round((1 - r.day_cost / r.day_rate) * 100)}%` : "—") },
  ],
  case_studies: [
    { key: "title", label: "Project", render: (r) => <><div className="font-semibold">{r.title}</div><div className="text-[12.5px] text-ink-muted line-clamp-2 max-w-xl">{r.summary}</div></> },
    { key: "industry", label: "Industry", render: (r) => <>{r.industry}<div className="text-[12px] text-ink-muted">{[r.region, r.year].filter(Boolean).join(" · ")}</div></> },
    { key: "technologies", label: "Technologies", render: (r) => <Tags v={r.technologies} max={4} /> },
    { key: "outcomes", label: "Outcomes", render: (r) => <div className="text-[12.5px] text-ink-soft line-clamp-3 max-w-xs">{(r.outcomes || []).join("; ")}</div> },
  ],
  accelerators: [
    { key: "name", label: "Accelerator", render: (r) => <><div className="font-semibold">{r.name}</div><div className="text-[12.5px] text-ink-muted line-clamp-2 max-w-xl">{r.description}</div></> },
    { key: "technologies", label: "Technologies", render: (r) => <Tags v={r.technologies} /> },
    { key: "effort_saving_pct", label: "Effort saving", cls: "text-right num", render: (r) => (r.effort_saving_pct ? `${r.effort_saving_pct}%` : "—") },
  ],
};

function Tags({ v, max = 5 }: { v: string[]; max?: number }) {
  if (!v?.length) return <span className="text-ink-faint">—</span>;
  return (
    <div className="flex flex-wrap gap-1 max-w-sm">
      {v.slice(0, max).map((t) => <span key={t} className="chip bg-paper border border-line text-ink-soft font-medium">{t}</span>)}
      {v.length > max && <span className="chip text-ink-muted">+{v.length - max}</span>}
    </div>
  );
}

function TemplateTab() {
  const { data, isLoading } = useQuery({ queryKey: ["template"], queryFn: () => api.get("/library/template") });
  const toast = useToast();
  if (isLoading) return <PageLoader />;
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <div className="card p-5">
        <div className="font-bold mb-3">Current template</div>
        {data ? (
          <div className="flex items-center gap-3">
            <FileText className="h-8 w-8 text-brand-500" />
            <div className="flex-1 min-w-0"><div className="font-semibold truncate">{data.filename}</div><div className="text-[12.5px] text-ink-muted">Uploaded {ago(data.created_at)}. {data.analysis?.how || `Placeholders: ${(data.analysis?.placeholders || []).join(", ") || "none"}`}</div></div>
            <button className="btn-outline" onClick={() => download("/library/template/download", data.filename).catch((e) => toast("error", e.message))}><Download className="h-4 w-4" /></button>
          </div>
        ) : <div className="text-sm text-ink-muted">No template yet. Proposals use a plain default layout until you upload one.</div>}
      </div>
      <div className="card p-5"><div className="font-bold mb-3">Replace template</div><TemplateUpload /></div>
    </div>
  );
}

export default function Library() {
  const { kind = "capabilities" } = useParams();
  const folderInput = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [up, setUp] = useState(false);
  const [folder, setFolder] = useState(false);
  const [drive, setDrive] = useState(false);
  const [pickedFiles, setPickedFiles] = useState<File[] | null>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({ queryKey: ["lib", kind], queryFn: () => api.get(`/library/${kind}`), enabled: kind !== "template" });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/library/${kind}/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["lib", kind] }); toast("ok", "Removed."); },
  });
  const rows = (data || []).filter((r: any) => !q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase()));
  const cols = COLS[kind];
  return (
    <div className="px-4 lg:px-8 py-6 max-w-[1500px]">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[260px]">
          <h1 className="font-display text-[32px] leading-tight text-brand-950">Knowledge library</h1>
          <p className="text-ink-muted text-sm mt-0.5">Everything RevenueForge knows about your company. Matches, estimates and proposals use only what's here.</p>
        </div>
        <input
          ref={folderInput}
          type="file"
          hidden
          multiple
          {...({ webkitdirectory: "", directory: "" } as any)}
          onChange={(event) => {
            const files = Array.from(event.target.files || []);
            event.target.value = "";
            if (files.length) {
              setPickedFiles(files);
              setFolder(true);
            }
          }}
        />
        <button className="btn-outline" onClick={() => folderInput.current?.click()}><FolderUp className="h-4 w-4" /> Import a folder</button>
        <button className="btn-outline" onClick={() => {
          window.open("https://drive.google.com/drive/my-drive", "_blank", "noopener,noreferrer");
          setDrive(true);
        }}>
          <GoogleDriveLogo /> Import from Google Drive
        </button>
      </div>
      <div className="mt-5 border-b border-line flex gap-1 overflow-x-auto scroll-thin">
        {TABS.map((t) => (
          <NavLink key={t.key} to={`/app/library/${t.key}`} className={() => clsx("px-3 h-10 inline-flex items-center text-[14px] font-medium border-b-2 -mb-px whitespace-nowrap",
            kind === t.key ? "border-brand-500 text-brand-800" : "border-transparent text-ink-muted hover:text-ink")}>{t.label}</NavLink>
        ))}
      </div>
      <div className="mt-4">
        {kind === "template" ? <TemplateTab /> : (
          <div className="card">
            <div className="px-3 py-2.5 border-b border-line flex flex-wrap items-center gap-2">
              <div className="relative flex-1 min-w-[200px] max-w-sm"><Search className="h-4 w-4 absolute left-2.5 top-2.5 text-ink-faint" /><input className="input h-9 pl-8" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} /></div>
              <span className="text-[13px] text-ink-muted num">{rows.length} of {data?.length ?? 0}</span>
              <div className="flex-1" />
              <button className="btn-primary" onClick={() => setUp(true)}><Upload className="h-4 w-4" /> Upload {KIND_INFO[kind].title.toLowerCase()}</button>
            </div>
            {isLoading ? <PageLoader /> : !rows.length ? (
              <Empty title={data?.length ? "Nothing matches your search" : `No ${KIND_INFO[kind].title.toLowerCase()} yet`} action={!data?.length && <button className="btn-primary" onClick={() => setUp(true)}>Upload</button>}>
                {!data?.length && KIND_INFO[kind].what}
              </Empty>
            ) : (
              <div className="overflow-x-auto max-h-[calc(100vh-280px)] scroll-thin">
                <table className="w-full min-w-[760px]">
                  <thead><tr>{cols.map((c) => <th key={c.key} className={clsx("th", c.cls?.includes("text-right") && "text-right")}>{c.label}</th>)}<th className="th w-10" /></tr></thead>
                  <tbody>
                    {rows.map((r: any) => (
                      <tr key={r.id} className="hover:bg-paper group">
                        {cols.map((c) => <td key={c.key} className={clsx("td", c.cls)}>{c.render ? c.render(r) : r[c.key] || "—"}</td>)}
                        <td className="td"><button className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-ink-faint hover:text-fit-gap-ink" aria-label="Remove" onClick={() => confirm("Remove this item from your library?") && del.mutate(r.id)}><Trash2 className="h-4 w-4" /></button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
      <Modal open={folder} onClose={() => { setFolder(false); setPickedFiles(null); }} title="Import a folder" xl>
        <FolderImport onDone={() => setFolder(false)} compact autoStartFiles={pickedFiles} />
      </Modal>
      {drive && <GoogleDriveImport onClose={() => setDrive(false)} onImported={() => { setDrive(false); setFolder(true); }} />}
      <Modal open={up} onClose={() => setUp(false)} title={`Upload ${KIND_INFO[kind]?.title.toLowerCase()}`} wide>
        {kind !== "template" && <UploadReview kind={kind} onImported={() => setTimeout(() => setUp(false), 900)} />}
      </Modal>
    </div>
  );
}

function GoogleDriveLogo() {
  return <img aria-hidden="true" src="/brand/google-drive.png" alt="" className="h-4 w-4 shrink-0" />;
}
