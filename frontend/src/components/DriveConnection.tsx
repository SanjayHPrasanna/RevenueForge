import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, LoaderCircle, RefreshCw, Unlink } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ago } from "../lib/format";
import { useAuthConfig } from "./GoogleButton";
import { driveSetupError, getDriveToken, listSupportedFiles, preloadGoogle, uploadDriveEntries, type DriveEntry } from "./GoogleDriveImport";
import { Modal, useToast } from "./ui";

/* The connected Google Drive folder: when it was last refreshed, and a Refresh button.
   Refresh asks Google for a fresh read-only token in this browser, lists the folder, and asks the server what changed.
   Nothing in the library changes until the person reviews the new and changed files and presses Import. */

type Status = { connected: boolean; folder?: { id: string; name: string }; connected_by?: string; last_refresh?: string; last_checked?: string; files?: number };
type Item = { id: string; path: string; kind?: string | null; imported?: boolean; records?: number; edited_in_app?: number | null };
type Plan = { new: Item[]; changed: Item[]; removed: Item[]; unchanged: number; up_to_date: boolean };

const KIND: Record<string, string> = { capabilities: "capabilities", skills: "people", certifications: "certificates", rates: "rates",
  case_studies: "case studies", accelerators: "accelerators", template: "proposal template" };

export default function DriveConnection({ onReview }: { onReview: (remove: string[]) => void }) {
  const { data: st } = useQuery({ queryKey: ["drive"], queryFn: () => api.get<Status>("/library/drive") });
  const { data: auth } = useAuthConfig();
  const role = useAuth().user?.role;
  const canRefresh = role === "admin" || role === "presales" || role === "architect" || role === "finance";
  const toast = useToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string>("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [entries, setEntries] = useState<DriveEntry[]>([]);
  const [token, setToken] = useState("");
  const [remove, setRemove] = useState<string[]>([]);
  const [error, setError] = useState("");

  useEffect(() => { if (st?.connected) preloadGoogle(); }, [st?.connected]);

  const disconnect = useMutation({
    mutationFn: () => api.del("/library/drive"),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["drive"] }); toast("ok", "Disconnected. Everything already imported stays in your library."); },
    onError: (e: any) => toast("error", e.message),
  });
  const removeOnly = useMutation({
    mutationFn: () => api.post<any>("/library/drive/remove", { ids: remove }),
    onSuccess: (r) => { setPlan(null); qc.invalidateQueries(); toast("ok", r.removed.length ? `Removed items from ${r.removed.length} deleted file${r.removed.length === 1 ? "" : "s"}.` : "Nothing removed."); },
    onError: (e: any) => toast("error", e.message),
  });

  if (!st?.connected || !st.folder) return null;
  const folder = st.folder;

  const refresh = async () => {
    if (!auth?.google_client_id) { toast("error", "Google sign-in isn't configured on this server."); return; }
    setError(""); setBusy("Asking Google for access…");
    try {
      const t = await getDriveToken(auth.google_client_id, "");
      setBusy("Reading the folder…");
      const list = await listSupportedFiles(t, folder.id, `${folder.name}/`);
      const p = await api.post<Plan>("/library/drive/plan", {
        folder_id: folder.id,
        files: list.map((e) => ({ id: e.id, path: e.path, modified: e.modifiedTime || "", version: e.version || "" })),
      });
      qc.invalidateQueries({ queryKey: ["drive"] });
      if (p.up_to_date) { toast("ok", `Up to date: no new, changed or deleted files in "${folder.name}".`); return; }
      setToken(t); setEntries(list); setRemove([]); setPlan(p);
    } catch (e: any) {
      const m = driveSetupError(e);
      setError(/not found|notFound|404/i.test(m)
        ? `Google says this account can't open "${folder.name}". Refresh with the Google account that connected it, or connect the folder again.`
        : m);
    } finally { setBusy(""); }
  };

  const download = async () => {
    if (!plan) return;
    const want = new Set([...plan.new, ...plan.changed].map((x) => x.id));
    const change: Record<string, "new" | "changed"> = {};
    plan.new.forEach((x) => (change[x.id] = "new"));
    plan.changed.forEach((x) => (change[x.id] = "changed"));
    setBusy("Downloading 0 files…"); setError("");
    try {
      const batch = await uploadDriveEntries(token, entries.filter((e) => want.has(e.id)), folder, change,
        (done, total) => setBusy(`Downloading ${done} of ${total} files…`), () => { /* review opens at the end */ });
      try { sessionStorage.setItem("rf.folderBatch", batch); } catch { /* review still opens */ }
      const chosen = remove;
      setPlan(null);
      onReview(chosen);
    } catch (e: any) { setError(driveSetupError(e)); } finally { setBusy(""); }
  };

  const fileCount = (plan?.new.length || 0) + (plan?.changed.length || 0);
  return (
    <>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-line bg-white px-3.5 py-2.5">
        <img aria-hidden="true" src="/brand/google-drive.png" alt="" className="h-4 w-4 shrink-0" />
        <div className="text-[13px] min-w-0">
          Connected to <b className="font-semibold">{folder.name}</b> in Google Drive
          <span className="text-ink-muted"> · {st.files} file{st.files === 1 ? "" : "s"} · {st.last_refresh ? `last refreshed ${ago(st.last_refresh)}` : "not refreshed yet"}
            {st.connected_by ? ` · connected by ${st.connected_by}` : ""}</span>
        </div>
        <div className="flex-1" />
        {busy && <span className="inline-flex items-center gap-1.5 text-[12.5px] text-brand-700"><LoaderCircle className="h-3.5 w-3.5 animate-spin" />{busy}</span>}
        {canRefresh && <>
          <button className="btn-outline h-8 text-[13px]" disabled={!!busy} onClick={refresh}><RefreshCw className="h-3.5 w-3.5" /> Refresh</button>
          <button className="btn-ghost h-8 text-[13px]" disabled={!!busy || disconnect.isPending}
            onClick={() => confirm(`Disconnect "${folder.name}"? Everything already imported stays in your library.`) && disconnect.mutate()}>
            <Unlink className="h-3.5 w-3.5" /> Disconnect</button>
        </>}
        {error && <div role="alert" className="basis-full text-[12.5px] text-fit-gap-ink">{error}</div>}
      </div>

      <Modal open={!!plan} onClose={() => !busy && setPlan(null)} title={`Changes in "${folder.name}"`} wide>
        {plan && (
          <div className="space-y-4 text-[13.5px]">
            <p className="text-ink-soft">
              {plan.new.length} new · {plan.changed.length} changed · {plan.removed.length} deleted from Drive · {plan.unchanged} unchanged.
              Nothing in your library changes until you review the files and press Import.
            </p>
            {plan.new.length > 0 && <Section title="New in Drive" items={plan.new.map((x) => ({ x, note: "" }))} />}
            {plan.changed.length > 0 && <Section title="Changed in Drive" items={plan.changed.map((x) => ({
              x,
              note: x.imported ? `replaces the ${x.records ?? 0} ${KIND[x.kind || ""] || "items"} it brought in` : "wasn't imported last time",
              warn: x.edited_in_app ? `${x.edited_in_app} of those were edited in the app since; the Drive version will replace those edits` : "",
            }))} />}
            {plan.removed.length > 0 && (
              <div>
                <div className="font-semibold mb-1.5">Deleted from Drive</div>
                <p className="text-[12.5px] text-ink-muted mb-2">Their items stay in your library unless you tick them here.</p>
                <div className="border border-line rounded-lg divide-y divide-line">
                  {plan.removed.map((x) => (
                    <label key={x.id} className="flex items-start gap-2.5 px-3 py-2 cursor-pointer">
                      <input type="checkbox" className="h-4 w-4 mt-0.5 accent-brand-600" disabled={!x.imported}
                        checked={remove.includes(x.id)} onChange={(e) => setRemove((r) => e.target.checked ? [...r, x.id] : r.filter((y) => y !== x.id))} />
                      <span className="min-w-0"><span className="break-all">{x.path}</span>
                        <span className="block text-[12px] text-ink-muted">{x.imported ? `Remove its ${x.records} ${KIND[x.kind || ""] || "items"} from the library` : "Nothing was imported from it"}</span></span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            {error && <div role="alert" className="text-[12.5px] text-fit-gap-ink">{error}</div>}
            <div className="flex flex-wrap items-center gap-3 pt-1">
              {fileCount > 0 ? (
                <button className="btn-primary" disabled={!!busy} onClick={download}>
                  {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  {busy || `Download ${fileCount} file${fileCount === 1 ? "" : "s"} and review`}
                </button>
              ) : (
                <button className="btn-primary" disabled={removeOnly.isPending || !remove.length} onClick={() => removeOnly.mutate()}>
                  {remove.length ? `Remove items from ${remove.length} deleted file${remove.length === 1 ? "" : "s"}` : "Tick the files to remove"}
                </button>
              )}
              <button className="btn-ghost" disabled={!!busy} onClick={() => setPlan(null)}>Not now</button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}

function Section({ title, items }: { title: string; items: { x: Item; note: string; warn?: string }[] }) {
  return (
    <div>
      <div className="font-semibold mb-1.5">{title}</div>
      <div className="border border-line rounded-lg divide-y divide-line">
        {items.map(({ x, note, warn }) => (
          <div key={x.id} className="px-3 py-2">
            <div className="break-all">{x.path}</div>
            {note && <div className="text-[12px] text-ink-muted">{note}</div>}
            {warn && <div className="text-[12px] text-fit-partial-ink inline-flex items-start gap-1 mt-0.5"><AlertTriangle className="h-3.5 w-3.5 mt-px shrink-0" />{warn}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
