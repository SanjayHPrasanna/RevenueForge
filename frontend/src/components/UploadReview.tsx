import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, download } from "../lib/api";
import { Dropzone, Spinner, useToast } from "./ui";

export const KIND_INFO: Record<string, { title: string; what: string; accept: string; hint: string; required?: boolean }> = {
  capabilities: { title: "Capabilities & services", what: "What your company offers: services, solutions, technologies and the industries you serve.", accept: ".xlsx,.csv,.docx,.pdf,.pptx", hint: "Excel or CSV in any layout, or a capability deck (Word, PDF, PowerPoint)", required: true },
  skills: { title: "Employee skills matrix", what: "Roles, grades, experience, skills and availability. Names are optional; employee codes are enough.", accept: ".xlsx,.csv", hint: "Excel or CSV: one row per person, a skills list or a rating grid both work", required: true },
  certifications: { title: "Certifications", what: "Company certifications (ISO, CMMI, SOC 2), partner tiers and individual certifications.", accept: ".xlsx,.csv,.docx,.pdf", hint: "Excel, CSV, Word or PDF" },
  rates: { title: "Rate card", what: "Sell rate and internal cost per role, level and delivery location. Hourly, daily or monthly rates are converted automatically.", accept: ".xlsx,.csv", hint: "Excel or CSV", required: true },
  case_studies: { title: "Case studies", what: "Past projects RevenueForge can cite as evidence. Upload a list, or one Word/PDF case study at a time.", accept: ".xlsx,.csv,.docx,.pdf,.pptx", hint: "Excel list, or Word / PDF / PowerPoint" },
  accelerators: { title: "Accelerators & IP", what: "Reusable assets that cut effort: frameworks, connectors, templates, tools.", accept: ".xlsx,.csv,.docx,.pdf", hint: "Excel, CSV, Word or PDF" },
};

const FIELD_LABEL: Record<string, string> = {
  name: "Name", service_line: "Service line", description: "Description", technologies: "Technologies", industries: "Industries", maturity: "Maturity",
  code: "Employee ID", role: "Role / designation", level: "Level / grade", years: "Years of experience", location: "Location", practice: "Practice / team",
  skills: "Skills list", secondary_skills: "Secondary skills", skill: "Skill (one per row)", proficiency: "Proficiency", certifications: "Certifications",
  availability: "Availability", kind: "Type", issuer: "Issuer", holders: "Holders", valid_until: "Valid until", day_rate: "Sell rate", day_cost: "Cost rate",
  currency: "Currency", title: "Title", client: "Client", industry: "Industry", region: "Region", year: "Year", summary: "Summary", outcomes: "Outcomes",
  effort_saving_pct: "Effort saving %",
};
const PREVIEW_COLS: Record<string, string[]> = {
  capabilities: ["name", "service_line", "technologies", "industries"],
  skills: ["code", "role", "level", "years", "location", "skills", "availability"],
  certifications: ["name", "kind", "issuer", "holders", "valid_until"],
  rates: ["role", "level", "location", "day_rate", "day_cost", "currency"],
  case_studies: ["title", "industry", "region", "technologies", "outcomes"],
  accelerators: ["name", "technologies", "effort_saving_pct"],
};

function cell(v: any): string {
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? `${x.name}${x.level ? ` (${x.level})` : ""}` : x)).join(", ");
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(1);
  return v ?? "";
}

export default function UploadReview({ kind, onImported, compact }: { kind: string; onImported?: (n: number) => void; compact?: boolean }) {
  const info = KIND_INFO[kind];
  const toast = useToast();
  const qc = useQueryClient();
  const [upload, setUpload] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [done, setDone] = useState<number | null>(null);

  const up = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.append("file", f);
      return api.upload(`/library/${kind}/upload`, fd);
    },
    onSuccess: (r) => {
      setUpload(r);
      setAnalysis(r.analysis);
      setDone(null);
    },
    onError: (e: any) => toast("error", e.message),
  });
  const imp = useMutation({
    mutationFn: () => api.post(`/library/uploads/${upload.id}/import`, { mode: "replace" }),
    onSuccess: (r) => {
      setDone(r.imported);
      qc.invalidateQueries();
      toast("ok", `Imported ${r.imported} ${info.title.toLowerCase()}. Knowledge graph updated.`);
      onImported?.(r.imported);
    },
    onError: (e: any) => toast("error", e.message),
  });

  const recs: any[] = analysis?.records_preview || [];

  return (
    <div className="space-y-4">
      {!compact && <p className="text-ink-soft text-[14.5px]">{info.what}</p>}
      {!upload && (
        <>
          <Dropzone accept={info.accept} onFile={(f) => up.mutate(f)} busy={up.isPending} hint={info.hint} />
          <button className="text-[13px] text-brand-700 font-semibold inline-flex items-center gap-1.5 hover:underline" onClick={() => download(`/library/${kind}/starter.xlsx`, `${kind}.xlsx`)}>
            <Download className="h-3.5 w-3.5" /> Download a starter spreadsheet
          </button>
        </>
      )}
      {upload && analysis && (
        <div className="card">
          <div className="px-4 py-3 border-b border-line flex flex-wrap items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-brand-600" />
            <div className="font-semibold text-sm truncate max-w-[50%]">{upload.filename}</div>
            <div className="text-[13px] text-ink-muted">
              {analysis.record_count} {analysis.record_count === 1 ? "record" : "records"} found
              {analysis.format === "table" && ` in ${analysis.row_count} rows`}
            </div>
            <div className="flex-1" />
            <button className="btn-ghost h-8" onClick={() => { setUpload(null); setAnalysis(null); setDone(null); }}>
              <RefreshCw className="h-3.5 w-3.5" /> Use another file
            </button>
          </div>

          <MappingAndPreview kind={kind} docId={upload.id} analysis={analysis} onAnalysis={setAnalysis} />

          <div className="px-4 py-3 flex flex-wrap items-center gap-3 border-t border-line">
            {done !== null ? (
              <div className="flex items-center gap-2 text-sm text-ok font-semibold">
                <CheckCircle2 className="h-4 w-4" /> {done} records imported
              </div>
            ) : (
              <>
                <button className="btn-primary" disabled={imp.isPending || !recs.length} onClick={() => imp.mutate()}>
                  {imp.isPending && <Spinner />} Import {analysis.record_count} records
                </button>
                <span className="text-[12.5px] text-ink-muted">Replaces any {info.title.toLowerCase()} imported earlier.</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Column matching (spreadsheets) and a preview of the records found. Used by single uploads and the folder import. */
export function MappingAndPreview({ kind, docId, analysis, onAnalysis }: { kind: string; docId: string; analysis: any; onAnalysis: (a: any) => void }) {
  const toast = useToast();
  const remap = useMutation({
    mutationFn: (body: any) => api.post(`/library/uploads/${docId}/remap`, body),
    onSuccess: (r) => onAnalysis(r.analysis),
    onError: (e: any) => toast("error", e.message),
  });
  const recs: any[] = analysis?.records_preview || [];
  const cols = PREVIEW_COLS[kind];
  return (
    <>
      {analysis.format === "table" && (
        <div className="px-4 py-4 border-b border-line-soft">
          <div className="text-[13px] font-semibold mb-1">How we read your columns</div>
          <div className="text-[12.5px] text-ink-muted mb-3">Change any mapping that looks wrong; the preview updates.</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-2.5">
            {(analysis.fields as string[]).map((f) => (
              <label key={f} className="text-[12.5px]">
                <span className="text-ink-soft font-medium">{FIELD_LABEL[f] || f}</span>
                <select
                  className="input h-8 mt-1 text-[13px]"
                  value={analysis.mapping?.[f] ?? ""}
                  onChange={(e) => {
                    const m = { ...analysis.mapping };
                    if (e.target.value === "") delete m[f];
                    else m[f] = Number(e.target.value);
                    remap.mutate({ mapping: m });
                  }}
                >
                  <option value="">Not in this file</option>
                  {(analysis.columns as string[]).map((c, i) => c && <option key={i} value={i}>{c}</option>)}
                </select>
              </label>
            ))}
          </div>
          {analysis.wide_skill_columns?.length > 0 && (
            <div className="mt-3 text-[12.5px] rounded bg-brand-50 text-brand-800 px-3 py-2">
              Rating grid detected: {analysis.wide_skill_columns.length} skill columns ({analysis.wide_skill_columns.slice(0, 6).map((i: number) => analysis.columns[i]).join(", ")}…) read as skill levels.
            </div>
          )}
          {analysis.missing?.length > 0 && (
            <div className="mt-3 text-[12.5px] rounded bg-[#FBF1DD] text-fit-partial-ink px-3 py-2">
              Still needed: {analysis.missing.map((m: string) => FIELD_LABEL[m] || m).join(", ")}. Pick the matching column above.
            </div>
          )}
        </div>
      )}

      <div className="overflow-x-auto max-h-[320px] scroll-thin">
        <table className="w-full min-w-[640px]">
          <thead>
            <tr>{cols.map((c) => <th key={c} className="th">{FIELD_LABEL[c]}</th>)}</tr>
          </thead>
          <tbody>
            {recs.slice(0, 25).map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c} className="td text-[13px] max-w-[280px]">
                    <div className="line-clamp-2">{c === "availability" ? `${cell(r[c])}%` : cell(r[c])}</div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function TemplateUpload({ onDone }: { onDone?: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [res, setRes] = useState<any>(null);
  const up = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.append("file", f);
      return api.upload(`/library/template/upload`, fd);
    },
    onSuccess: (r) => {
      setRes(r);
      qc.invalidateQueries();
      toast("ok", "Proposal template saved.");
      onDone?.();
    },
    onError: (e: any) => toast("error", e.message),
  });
  return (
    <div className="space-y-4">
      <p className="text-ink-soft text-[14.5px]">
        Your Word template keeps its branding, styles, header and footer. RevenueForge works with either kind of template: one with your own
        section headings and placeholders such as <code className="mx-1 text-[12.5px] bg-paper px-1 rounded">[Insert Solution Overview Here]</code>,
        which it fills section by section, or one with a{" "}
        <code className="text-[12.5px] bg-paper px-1 rounded">{"{{CONTENT}}"}</code> marker where the whole proposal goes.{" "}
        <code className="text-[12.5px] bg-paper px-1 rounded">{"{{TITLE}}"}</code>,{" "}
        <code className="text-[12.5px] bg-paper px-1 rounded">{"{{CLIENT}}"}</code> and{" "}
        <code className="text-[12.5px] bg-paper px-1 rounded">{"{{DATE}}"}</code> are filled anywhere, including headers.
      </p>
      <Dropzone accept=".docx" onFile={(f) => up.mutate(f)} busy={up.isPending} hint="Word (.docx)" label="Drop your proposal template or browse" />
      {res && (
        <div className="card px-4 py-3 text-sm flex flex-wrap gap-x-6 gap-y-1">
          <span className="font-semibold flex items-center gap-1.5"><CheckCircle2 className="h-4 w-4 text-ok" /> {res.filename}</span>
          <span className="text-ink-muted">{res.analysis.how || `Placeholders: ${res.analysis.placeholders.join(", ") || "none"}`}</span>
        </div>
      )}
    </div>
  );
}
