import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, FileSpreadsheet, FileText, FolderOpen, FolderUp, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { Modal, Spinner, useToast } from "./ui";
import { KIND_INFO, MappingAndPreview } from "./UploadReview";

/* Pick (or drop) one folder; every supported file inside is uploaded, sorted by type in the background,
   and shown on one review screen. Nothing reaches the library until "Import" is pressed. */

const OK_EXT = [".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".pptx", ".txt", ".md"];
const TYPE_ORDER = ["capabilities", "skills", "certifications", "rates", "case_studies", "accelerators", "template"];
const TYPE_LABEL: Record<string, string> = { ...Object.fromEntries(Object.entries(KIND_INFO).map(([k, v]) => [k, v.title])), template: "Proposal template" };
const BATCH_KEY = "rf.folderBatch";

type Picked = { file: File; path: string };
type Row = {
  id: string; path: string; filename: string; status: string; type: string | null; confidence: string | null; reason: string;
  records: number; format: string | null; missing: string[]; error: string; how?: string; ai?: string | null;
};

const readKey = () => { try { return sessionStorage.getItem(BATCH_KEY) || ""; } catch { return ""; } };
const writeKey = (v: string) => { try { v ? sessionStorage.setItem(BATCH_KEY, v) : sessionStorage.removeItem(BATCH_KEY); } catch { /* storage unavailable */ } };

const wanted = (name: string) => !/^(~\$|\.)/.test(name) && OK_EXT.some((e) => name.toLowerCase().endsWith(e));

async function filesFromDrop(items: DataTransferItemList): Promise<Picked[]> {
  const out: Picked[] = [];
  const walk = async (entry: any, prefix: string): Promise<void> => {
    if (!entry) return;
    if (entry.isFile) {
      const file: File = await new Promise((res, rej) => entry.file(res, rej));
      out.push({ file, path: prefix + file.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch: any[];
      do {
        batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        for (const e of batch) await walk(e, `${prefix}${entry.name}/`);
      } while (batch.length);
    }
  };
  const entries = Array.from(items).map((i) => (i as any).webkitGetAsEntry?.()).filter(Boolean);
  for (const e of entries) await walk(e, "");
  return out;
}

function chunks(list: Picked[]): Picked[][] {
  const out: Picked[][] = [];
  let cur: Picked[] = [], size = 0;
  for (const p of list) {
    if (cur.length && (cur.length >= 8 || size + p.file.size > 20 * 1024 * 1024)) { out.push(cur); cur = []; size = 0; }
    cur.push(p); size += p.file.size;
  }
  if (cur.length) out.push(cur);
  return out;
}

async function uploadPart(part: Picked[], batch: string): Promise<{ batch: string; skipped: { path: string; reason: string }[] }> {
  const fd = new FormData();
  part.forEach((p) => { fd.append("files", p.file, p.file.name); fd.append("paths", p.path); });
  if (batch) fd.append("batch", batch);
  return api.upload("/library/folder", fd);
}

export default function FolderImport({ onDone, compact, autoStartFiles }: {
  onDone?: () => void;
  compact?: boolean;
  autoStartFiles?: File[] | null;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [batch, setBatch] = useState<string>(readKey);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [skipped, setSkipped] = useState<{ path: string; reason: string }[]>([]);
  const [over, setOver] = useState(false);
  const [replace, setReplace] = useState(true);
  const [fix, setFix] = useState<Row | null>(null);
  const [fixAnalysis, setFixAnalysis] = useState<any>(null);
  const [result, setResult] = useState<any>(null);

  const status = useQuery({
    queryKey: ["folder", batch],
    queryFn: () => api.get<{ files: Row[]; pending: number; imported: number }>(`/library/folder/${batch}`),
    enabled: !!batch && !progress,
    refetchInterval: (q) => {
      const d = q.state.data;
      if (!d) return 1500;
      if (d.pending > 0) return 1500;
      return d.files.some((f) => f.ai === "pending" && f.status === "review") ? 4000 : false;
    },
  });

  const start = async (picked: Picked[]) => {
    const files = picked.filter((p) => wanted(p.file.name));
    const ignored = picked.length - files.length;
    if (!files.length) {
      toast("error", picked.length ? "No spreadsheets, Word, PDF or PowerPoint files in that folder." : "That folder is empty.");
      return;
    }
    if (files.length > 300) {
      toast("error", "That's more than 300 files. Pick the folder that holds just the company knowledge files.");
      return;
    }
    setResult(null);
    setSkipped(ignored ? [{ path: `${ignored} other file${ignored === 1 ? "" : "s"}`, reason: "Images, zips and other types are left out" }] : []);
    setProgress({ done: 0, total: files.length });
    let id = "";
    try {
      for (const part of chunks(files)) {
        const r = await uploadPart(part, id);
        id = r.batch;
        setSkipped((s) => [...s, ...r.skipped]);
        setProgress((p) => p && { ...p, done: p.done + part.length });
      }
      setBatch(id); writeKey(id);
    } catch (e: any) {
      toast("error", e.message);
      if (id) { setBatch(id); writeKey(id); }
    } finally {
      setProgress(null);
    }
  };

  useEffect(() => {
    if (autoStartFiles?.length) {
      start(autoStartFiles.map((file) => ({ file, path: (file as any).webkitRelativePath || file.name })));
    }
  }, [autoStartFiles]);

  const setType = useMutation({
    mutationFn: ({ row, type }: { row: Row; type: string | null }) => api.post(`/library/folder/${batch}/${row.id}/type`, { type }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["folder", batch] }),
    onError: (e: any) => toast("error", e.message),
  });
  const imp = useMutation({
    mutationFn: () => api.post(`/library/folder/${batch}/import`, { replace }),
    onSuccess: (r) => {
      setResult(r);
      writeKey("");
      qc.invalidateQueries();
      toast("ok", `Imported ${r.files} file${r.files === 1 ? "" : "s"}. Knowledge graph updated.`);
    },
    onError: (e: any) => toast("error", e.message),
  });

  const reset = () => { setBatch(""); writeKey(""); setResult(null); setSkipped([]); };

  // ---------------------------------------------------------------- done
  if (result) {
    const c = result.counts as Record<string, number>;
    return (
      <div className="rounded-xl border border-ok/30 bg-ok-bg/60 p-5">
        <div className="flex items-center gap-2 font-semibold text-ok"><CheckCircle2 className="h-5 w-5" /> {result.files} files imported into your knowledge library</div>
        <div className="mt-3 grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
          {TYPE_ORDER.filter((k) => c[k]).map((k) => (
            <div key={k} className="rounded-lg bg-white border border-line px-3 py-2">
              <div className="num text-[20px] font-bold text-brand-900 leading-none">{k === "template" ? "✓" : c[k]}</div>
              <div className="text-[12.5px] text-ink-muted mt-1">{TYPE_LABEL[k]}</div>
            </div>
          ))}
        </div>
        {result.problems?.length > 0 && (
          <div className="mt-3 text-[12.5px] text-fit-partial-ink">Not imported: {result.problems.map((p: any) => `${p.path} (${p.reason})`).join("; ")}</div>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {onDone && <button className="btn-primary" onClick={onDone}>Continue</button>}
          <button className="btn-outline" onClick={reset}>Import another folder</button>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- pick
  if (!batch || progress) {
    return (
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={async (e) => { e.preventDefault(); setOver(false); if (!progress) start(await filesFromDrop(e.dataTransfer.items)); }}
        className={clsx("rounded-xl border-2 border-dashed text-center transition-colors", compact ? "px-5 py-6" : "px-6 py-10",
          over ? "border-brand-500 bg-brand-50" : "border-brand-200 bg-gradient-to-b from-brand-50/70 to-white")}
      >
        <input ref={input} type="file" hidden multiple {...({ webkitdirectory: "", directory: "" } as any)}
          onChange={(e) => { const fs = Array.from(e.target.files || []); e.target.value = ""; start(fs.map((f) => ({ file: f, path: (f as any).webkitRelativePath || f.name }))); }} />
        {progress ? (
          <div className="max-w-sm mx-auto">
            <Spinner className="h-7 w-7 text-brand-500 mx-auto" />
            <div className="mt-3 font-semibold">Uploading {progress.done} of {progress.total} files…</div>
            <div className="mt-3 h-2 rounded-full bg-line overflow-hidden"><div className="h-full bg-brand-500 transition-all" style={{ width: `${(progress.done / progress.total) * 100}%` }} /></div>
          </div>
        ) : (
          <>
            <div className="mx-auto h-12 w-12 rounded-2xl bg-white border border-brand-100 shadow-card grid place-items-center"><FolderUp className="h-6 w-6 text-brand-600" /></div>
            <div className="mt-3 font-display text-[22px] text-brand-950 leading-tight">Import your whole knowledge folder</div>
            <p className="mt-1.5 text-[14px] text-ink-soft max-w-xl mx-auto">
              Pick the folder with your capability decks, skills matrix, rate card, certifications, case studies and proposal template.
              RevenueForge reads every file and works out what each one is. You check it on one screen before anything is imported.
            </p>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
              <button className="btn-primary h-11 px-6" onClick={() => input.current?.click()}><FolderOpen className="h-4 w-4" /> Choose folder</button>
              <span className="text-[13px] text-ink-muted">or drag the folder here</span>
            </div>
            <div className="mt-4 text-[12px] text-ink-muted">Excel, CSV, Word, PDF and PowerPoint, including sub-folders. Images, zips and temporary files are skipped.</div>
          </>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------- review
  const rows = [...(status.data?.files || [])].sort((a, b) => {
    const ia = a.type ? TYPE_ORDER.indexOf(a.type) : 99, ib = b.type ? TYPE_ORDER.indexOf(b.type) : 99;
    return ia - ib || a.path.localeCompare(b.path);
  });
  const pending = status.data?.pending ?? 0;
  const live = rows.filter((r) => r.status !== "imported");
  const ready = live.filter((r) => r.status === "review" && r.type && (r.type === "template" ? !r.error : r.records > 0));
  const attention = live.filter((r) => r.status === "failed" || (r.status === "review" && r.type && (r.type === "template" ? !!r.error : r.records === 0 || r.missing.length > 0)) || (r.status === "review" && r.type && r.confidence === "low"));
  const left = live.filter((r) => r.status === "review" && !r.type);
  const templates = ready.filter((r) => r.type === "template");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="font-semibold text-[15px]">{rows.length} files from your folder</div>
        <Stat n={ready.length} label="ready" cls="text-ok" />
        <Stat n={attention.length} label="to check" cls="text-fit-partial-ink" />
        <Stat n={left.length + skipped.length} label="left out" cls="text-ink-muted" />
        {pending > 0 && <span className="inline-flex items-center gap-1.5 text-[13px] text-brand-700"><Spinner className="h-3.5 w-3.5" /> Reading {pending} more…</span>}
        <div className="flex-1" />
        <button className="btn-ghost h-8 text-[13px]" onClick={reset}><RefreshCw className="h-3.5 w-3.5" /> Start over</button>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto max-h-[min(60vh,560px)] scroll-thin">
          <table className="w-full min-w-[760px]">
            <thead className="sticky top-0 z-10 bg-white">
              <tr><th className="th">File</th><th className="th w-[230px]">What it is</th><th className="th">What we found</th></tr>
            </thead>
            <tbody>
              {status.isLoading && <tr><td colSpan={3} className="td text-center py-8"><Spinner className="h-5 w-5 mx-auto text-brand-500" /></td></tr>}
              {rows.map((r) => {
                const folder = r.path.includes("/") ? r.path.slice(0, r.path.lastIndexOf("/")) : "";
                const Icon = /\.(xlsx|xlsm|csv)$/i.test(r.filename) ? FileSpreadsheet : FileText;
                return (
                  <tr key={r.id} className={clsx("align-top", !r.type && r.status === "review" && "bg-paper/60")}>
                    <td className="td">
                      <div className="flex items-start gap-2.5 min-w-0">
                        <Icon className={clsx("h-4 w-4 mt-0.5 shrink-0", r.type ? "text-brand-600" : "text-ink-faint")} />
                        <div className="min-w-0">
                          <div className={clsx("font-medium text-[13.5px] break-all", !r.type && r.status === "review" && "text-ink-muted")}>{r.filename}</div>
                          {folder && <div className="text-[11.5px] text-ink-faint truncate max-w-[340px]">{folder}</div>}
                        </div>
                      </div>
                    </td>
                    <td className="td">
                      {r.status === "analyzing" ? (
                        <span className="inline-flex items-center gap-1.5 text-[13px] text-ink-muted"><Spinner className="h-3.5 w-3.5" /> Reading…</span>
                      ) : r.status === "imported" ? (
                        <span className="text-[13px] font-semibold">{r.type ? TYPE_LABEL[r.type] : "—"}</span>
                      ) : (
                        <select
                          className={clsx("input h-8 text-[13px] py-0", r.type && r.confidence === "low" && "border-fit-partial")}
                          value={r.type ?? ""}
                          disabled={setType.isPending || r.status === "failed"}
                          onChange={(e) => setType.mutate({ row: r, type: e.target.value || null })}
                        >
                          {TYPE_ORDER.map((k) => <option key={k} value={k}>{TYPE_LABEL[k]}</option>)}
                          <option value="">Don't import</option>
                        </select>
                      )}
                    </td>
                    <td className="td text-[13px]"><Finding r={r} onFix={() => { setFix(r); setFixAnalysis(null); api.get(`/library/uploads/${r.id}`).then((d: any) => setFixAnalysis(d.analysis)); }} /></td>
                  </tr>
                );
              })}
              {skipped.map((s, i) => (
                <tr key={`s${i}`} className="bg-paper/60">
                  <td className="td text-[13px] text-ink-muted break-all">{s.path}</td>
                  <td className="td text-[13px] text-ink-muted">Skipped</td>
                  <td className="td text-[12.5px] text-ink-muted">{s.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-line flex flex-wrap items-center gap-x-4 gap-y-2 bg-white">
          <button className="btn-primary" disabled={pending > 0 || imp.isPending || !ready.length} onClick={() => imp.mutate()}>
            {imp.isPending && <Spinner />} Import {ready.length} file{ready.length === 1 ? "" : "s"}
          </button>
          <label className="inline-flex items-center gap-2 text-[13px] text-ink-soft cursor-pointer">
            <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
            Replace what's already in the library for these sections
          </label>
          {templates.length > 1 && <span className="text-[12.5px] text-fit-partial-ink">Only the first proposal template is used. Set the others to "Don't import".</span>}
          {pending > 0 && <span className="text-[12.5px] text-ink-muted">You can import once every file has been read.</span>}
        </div>
      </div>

      <Modal open={!!fix} onClose={() => { setFix(null); qc.invalidateQueries({ queryKey: ["folder", batch] }); }} title={fix ? `Match columns: ${fix.filename}` : ""} xl>
        {fix && !fixAnalysis && <div className="py-10 text-center"><Spinner className="h-6 w-6 mx-auto text-brand-500" /></div>}
        {fix && fixAnalysis && fix.type && fix.type !== "template" && (
          <div className="card">
            <MappingAndPreview kind={fix.type} docId={fix.id} analysis={fixAnalysis} onAnalysis={setFixAnalysis} />
            <div className="px-4 py-3 border-t border-line flex items-center gap-3">
              <button className="btn-primary" onClick={() => { setFix(null); qc.invalidateQueries({ queryKey: ["folder", batch] }); }}>Done</button>
              <span className="text-[12.5px] text-ink-muted">{fixAnalysis.record_count} records will be imported from this file.</span>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function Stat({ n, label, cls }: { n: number; label: string; cls: string }) {
  return <span className="text-[13px]"><span className={clsx("num font-bold", cls)}>{n}</span> <span className="text-ink-muted">{label}</span></span>;
}

function Finding({ r, onFix }: { r: Row; onFix: () => void }) {
  if (r.status === "analyzing") return <span className="text-ink-faint">…</span>;
  if (r.status === "imported") return <span className="inline-flex items-center gap-1.5 text-ok font-semibold"><CheckCircle2 className="h-4 w-4" /> Imported</span>;
  if (r.status === "failed") return <span className="inline-flex items-start gap-1.5 text-fit-gap-ink"><XCircle className="h-4 w-4 mt-px shrink-0" /> Couldn't read this file{r.error ? `: ${r.error.slice(0, 120)}` : "."}</span>;
  if (!r.type) return <span className="text-ink-muted">{r.reason || "Won't be imported."}</span>;
  const ai = r.ai === "pending" && (
    <div className="mt-1 inline-flex items-center gap-1.5 text-[12px] text-brand-700"><Spinner className="h-3 w-3" /> AI is reading it for more detail. You don't need to wait.</div>
  );
  const check = r.confidence === "low" && <div className="mt-1 inline-flex items-center gap-1 text-[12px] text-fit-partial-ink"><AlertTriangle className="h-3.5 w-3.5" /> Best guess. Check the type.</div>;
  if (r.type === "template") {
    return r.error
      ? <span className="text-fit-partial-ink">{r.error}</span>
      : <div><div className="inline-flex items-center gap-1.5 text-ink"><CheckCircle2 className="h-4 w-4 text-ok" /> Proposal template</div><div className="text-[12px] text-ink-muted mt-0.5 line-clamp-2">{r.how}</div>{check}</div>;
  }
  const table = r.format === "table";
  if (r.records === 0 || (table && r.missing.length)) {
    return (
      <div>
        <div className="inline-flex items-center gap-1.5 text-fit-partial-ink"><AlertTriangle className="h-4 w-4" />
          {r.records === 0 ? "Nothing found yet" : `${r.records} records, but some columns aren't matched`}
        </div>
        {table ? (
          <button className="block mt-1 text-[12.5px] font-semibold text-brand-700 hover:underline" onClick={onFix}>Match columns</button>
        ) : (
          r.ai !== "pending" && <div className="text-[12px] text-ink-muted mt-0.5">Try another type, or choose "Don't import".</div>
        )}
        {ai}
        {check}
      </div>
    );
  }
  return (
    <div>
      <div className="inline-flex items-center gap-1.5"><CheckCircle2 className="h-4 w-4 text-ok" /> <span className="num font-semibold">{r.records}</span> {r.records === 1 ? "record" : "records"}</div>
      {table && <button className="ml-2 text-[12px] text-brand-700 hover:underline" onClick={onFix}>Review columns</button>}
      {ai && <div>{ai}</div>}
      {check}
    </div>
  );
}
