import { useState } from "react";
import { ChevronRight, Folder, HardDriveDownload, LoaderCircle } from "lucide-react";
import { api } from "../lib/api";
import { useAuthConfig } from "./GoogleButton";
import { Modal } from "./ui";

const DRIVE_API = "https://www.googleapis.com/drive/v3";
const FOLDER_MIME = "application/vnd.google-apps.folder";
const BATCH_KEY = "rf.folderBatch";
const OK_EXT = [".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".pptx", ".txt", ".md"];
const MAX_FILES = 300;
const MAX_FILE_SIZE = 40 * 1024 * 1024;

const EXPORTS: Record<string, { extension: string; mimeType: string }> = {
  "application/vnd.google-apps.document": { extension: ".docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
  "application/vnd.google-apps.spreadsheet": { extension: ".xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
  "application/vnd.google-apps.presentation": { extension: ".pptx", mimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation" },
};

type DriveFolder = { id: string; name: string };
type DriveFile = { id: string; name: string; mimeType: string; size?: string };
type DriveEntry = DriveFile & { path: string };

let gisPromise: Promise<void> | null = null;

declare global {
  interface Window {
    google?: any;
  }
}

function loadGis(): Promise<void> {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  gisPromise ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      gisPromise = null;
      reject(new Error("Couldn't load Google authorization. Check your internet connection."));
    };
    document.head.appendChild(script);
  });
  return gisPromise;
}

async function driveRequest<T>(token: string, url: string): Promise<T> {
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.error?.message || "Couldn't read files from Google Drive.");
  return body as T;
}

function driveSetupError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || "");
  if (/origin[_ ]mismatch|origin.*not allowed|unauthorized.client/i.test(message)) {
    return `Google rejected this app's origin (${window.location.origin}). Add that exact origin under Google Cloud Console → Google Auth Platform → Clients → your OAuth client → Authorized JavaScript origins, then retry.`;
  }
  if (/service_disabled|has not been used|disabled/i.test(message)) {
    return "Google Drive API isn't enabled for this Google Cloud project. Enable it in Google Cloud Console, then retry.";
  }
  return message || "Couldn't connect to Google Drive.";
}

async function listFolders(token: string, parentId: string): Promise<DriveFolder[]> {
  const result: DriveFolder[] = [];
  let pageToken = "";
  do {
    const params = new URLSearchParams({
      q: `'${parentId}' in parents and mimeType = '${FOLDER_MIME}' and trashed = false`,
      fields: "nextPageToken,files(id,name)",
      pageSize: "1000",
      orderBy: "name",
      supportsAllDrives: "true",
      includeItemsFromAllDrives: "true",
      corpora: "allDrives",
    });
    if (pageToken) params.set("pageToken", pageToken);
    const page = await driveRequest<{ files?: DriveFolder[]; nextPageToken?: string }>(token, `${DRIVE_API}/files?${params}`);
    result.push(...(page.files || []));
    pageToken = page.nextPageToken || "";
  } while (pageToken);
  return result;
}

function exportedName(file: DriveFile): string {
  const exportInfo = EXPORTS[file.mimeType];
  return exportInfo && !file.name.toLowerCase().endsWith(exportInfo.extension)
    ? `${file.name}${exportInfo.extension}`
    : file.name;
}

async function listSupportedFiles(token: string, folderId: string, prefix: string, depth = 0, visited = new Set<string>()): Promise<DriveEntry[]> {
  if (depth > 30) throw new Error("This Google Drive folder is nested too deeply to import.");
  if (visited.has(folderId)) return [];
  visited.add(folderId);

  const result: DriveEntry[] = [];
  let pageToken = "";
  do {
    const params = new URLSearchParams({
      q: `'${folderId}' in parents and trashed = false`,
      fields: "nextPageToken,files(id,name,mimeType,size)",
      pageSize: "1000",
      orderBy: "name",
      supportsAllDrives: "true",
      includeItemsFromAllDrives: "true",
      corpora: "allDrives",
    });
    if (pageToken) params.set("pageToken", pageToken);
    const page = await driveRequest<{ files?: DriveFile[]; nextPageToken?: string }>(token, `${DRIVE_API}/files?${params}`);
    for (const file of page.files || []) {
      if (file.mimeType === FOLDER_MIME) {
        result.push(...await listSupportedFiles(token, file.id, `${prefix}${file.name}/`, depth + 1, visited));
        if (result.length > MAX_FILES) throw new Error(`This folder has more than ${MAX_FILES} supported files. Choose a smaller folder.`);
        continue;
      }
      const name = exportedName(file);
      if (!EXPORTS[file.mimeType] && !OK_EXT.some((ext) => name.toLowerCase().endsWith(ext))) continue;
      result.push({ ...file, path: `${prefix}${name}` });
      if (result.length > MAX_FILES) throw new Error(`This folder has more than ${MAX_FILES} supported files. Choose a smaller folder.`);
    }
    pageToken = page.nextPageToken || "";
  } while (pageToken);
  return result;
}

async function uploadDriveFolder(
  token: string,
  folder: DriveFolder,
  folderPath: DriveFolder[],
  onProgress: (done: number, total: number) => void,
  onBatch: (batch: string) => void,
): Promise<string> {
  const prefix = folderPath.length > 1 ? `${folderPath.slice(1).map((part) => part.name).join("/")}/` : "";
  const entries = await listSupportedFiles(token, folder.id, prefix);
  if (!entries.length) throw new Error("No supported files were found in this Google Drive folder.");

  let batch = "";
  let done = 0;
  let part: { file: File; path: string }[] = [];
  let size = 0;
  onProgress(0, entries.length);

  const send = async () => {
    if (!part.length) return;
    const form = new FormData();
    part.forEach(({ file, path }) => {
      form.append("files", file, file.name);
      form.append("paths", path);
    });
    if (batch) form.append("batch", batch);
    const response = await api.upload<{ batch: string }>("/library/folder", form);
    batch = response.batch;
    try { sessionStorage.setItem(BATCH_KEY, batch); } catch { /* folder review still opens for this session */ }
    onBatch(batch);
    done += part.length;
    onProgress(done, entries.length);
    part = [];
    size = 0;
  };

  for (const entry of entries) {
    if (entry.size && Number(entry.size) > MAX_FILE_SIZE) {
      throw new Error(`"${entry.name}" is larger than the 40 MB upload limit.`);
    }
    const exportInfo = EXPORTS[entry.mimeType];
    const fileUrl = exportInfo
      ? `${DRIVE_API}/files/${encodeURIComponent(entry.id)}/export?mimeType=${encodeURIComponent(exportInfo.mimeType)}`
      : `${DRIVE_API}/files/${encodeURIComponent(entry.id)}?alt=media`;
    const response = await fetch(fileUrl, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) {
      let message = `Couldn't download "${entry.name}" from Google Drive.`;
      try { message = (await response.json()).error?.message || message; } catch { /* response isn't JSON */ }
      throw new Error(message);
    }
    const blob = await response.blob();
    if (blob.size > MAX_FILE_SIZE) throw new Error(`"${entry.name}" is larger than the 40 MB upload limit.`);

    const name = entry.path.split("/").pop() || entry.name;
    const file = new File([blob], name, { type: blob.type });
    if (part.length && (part.length >= 8 || size + file.size > 20 * 1024 * 1024)) await send();
    part.push({ file, path: entry.path });
    size += file.size;
    if (part.length >= 8 || size >= 20 * 1024 * 1024) await send();
  }
  await send();
  if (!batch) throw new Error("Google Drive returned no import batch.");
  return batch;
}

export default function GoogleDriveImport({ onImported, onClose }: { onImported: () => void; onClose: () => void }) {
  const { data: auth } = useAuthConfig();
  const [open, setOpen] = useState(true);
  const [token, setToken] = useState("");
  const [path, setPath] = useState<DriveFolder[]>([]);
  const [folders, setFolders] = useState<DriveFolder[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [partialBatch, setPartialBatch] = useState("");
  const [error, setError] = useState("");

  const close = () => {
    if (busy) return;
    setOpen(false);
    onClose();
  };

  const connect = async () => {
    if (!auth?.google_client_id) return;
    setBusy(true);
    setError("");
    try {
      await loadGis();
      const accessToken = await new Promise<string>((resolve, reject) => {
        const client = window.google.accounts.oauth2.initTokenClient({
          client_id: auth.google_client_id,
          scope: "https://www.googleapis.com/auth/drive.readonly",
          callback: (response: any) => {
            if (response.error || !response.access_token) reject(new Error(response.error_description || response.error || "Google didn't provide a Drive access token."));
            else resolve(response.access_token);
          },
          error_callback: (response: any) => reject(new Error(response.message || "Google Drive authorization was cancelled.")),
        });
        client.requestAccessToken({ prompt: "select_account" });
      });
      const root = { id: "root", name: "My Drive" };
      setToken(accessToken);
      setPath([root]);
      setFolders(await listFolders(accessToken, root.id));
    } catch (e: any) {
      setError(driveSetupError(e));
    } finally {
      setBusy(false);
    }
  };

  const navigateTo = async (nextPath: DriveFolder[]) => {
    const target = nextPath[nextPath.length - 1];
    setBusy(true);
    setError("");
    try {
      setFolders(await listFolders(token, target.id));
      setPath(nextPath);
    } catch (e: any) {
      setError(driveSetupError(e));
    } finally {
      setBusy(false);
    }
  };

  const importFolder = async () => {
    const folder = path[path.length - 1];
    if (!token || !folder) return;
    setBusy(true);
    setError("");
    setPartialBatch("");
    let batchUploaded = "";
    try { sessionStorage.removeItem(BATCH_KEY); } catch { /* folder review still opens for this session */ }
    try {
      const batch = await uploadDriveFolder(
        token,
        folder,
        path,
        (done, total) => setProgress({ done, total }),
        (batch) => { batchUploaded = batch; setPartialBatch(batch); },
      );
      try { sessionStorage.setItem(BATCH_KEY, batch); } catch { /* folder review still opens for this session */ }
      setOpen(false);
      onImported();
    } catch (e: any) {
      const message = driveSetupError(e);
      setError(batchUploaded ? `${message} Some files already uploaded and can still be reviewed.` : message);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  return (
    <Modal open={open} onClose={close} title="Import from Google Drive">
      {!token ? (
        <div>
          <p className="text-[13.5px] text-ink-soft mb-4">
            Connect to Google Drive and choose a folder. RevenueForge requests read-only access and sends supported files to your normal review screen.
          </p>
          <p className="text-[12px] text-ink-muted mb-4">
            Setup required: enable the Google Drive API and authorize <code className="font-mono">{window.location.origin}</code> as a JavaScript origin on the Google OAuth client.
          </p>
          {!auth?.google_client_id && <p className="text-[13px] text-fit-partial-ink mb-3">Google sign-in isn't configured on this server.</p>}
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary" disabled={busy || !auth?.google_client_id} onClick={connect}>
              {busy && <LoaderCircle className="h-4 w-4 animate-spin" />} Connect Google Drive
            </button>
            <a className="text-[13px] text-brand-700 hover:underline" href="https://drive.google.com/drive/my-drive" target="_blank" rel="noreferrer">Open Google Drive in a new tab</a>
          </div>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1 text-[13px] mb-3">
            {path.map((folder, index) => (
              <span key={folder.id} className="inline-flex items-center gap-1">
                {index > 0 && <ChevronRight className="h-3.5 w-3.5 text-ink-faint" />}
                <button className="text-brand-700 hover:underline" disabled={busy || index === path.length - 1}
                  onClick={() => navigateTo(path.slice(0, index + 1))}>{folder.name}</button>
              </span>
            ))}
          </div>
          <div className="max-h-[40vh] min-h-28 overflow-auto border border-line rounded-lg">
            {busy && <div className="py-8 text-center text-[13px] text-ink-muted"><LoaderCircle className="h-5 w-5 animate-spin inline mr-2" />{progress ? `Importing ${progress.done} of ${progress.total} files…` : "Loading folders…"}</div>}
            {!busy && !folders.length && <div className="py-8 text-center text-[13px] text-ink-muted">No subfolders here. You can import this folder.</div>}
            {!busy && folders.map((folder) => (
              <button key={folder.id} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-[13px] hover:bg-paper border-b border-line last:border-0"
                onClick={() => navigateTo([...path, folder])}>
                <Folder className="h-4 w-4 text-brand-600 shrink-0" />
                <span className="truncate">{folder.name}</span>
                <ChevronRight className="h-4 w-4 text-ink-faint ml-auto shrink-0" />
              </button>
            ))}
          </div>
          {progress && <div className="mt-3 h-2 rounded-full bg-line overflow-hidden"><div className="h-full bg-brand-500 transition-all" style={{ width: `${(progress.done / progress.total) * 100}%` }} /></div>}
          {error && <div role="alert" className="mt-3 text-[12.5px] text-fit-gap-ink">{error}</div>}
          {partialBatch && !busy && (
            <button className="mt-3 text-[13px] font-semibold text-brand-700 hover:underline" onClick={() => { setOpen(false); onImported(); }}>
              Review files already uploaded
            </button>
          )}
          <div className="mt-4 flex justify-between gap-3">
            <button className="btn-ghost" disabled={busy || path.length < 2} onClick={() => navigateTo(path.slice(0, -1))}>Back</button>
            <button className="btn-primary" disabled={busy} onClick={importFolder}>
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <HardDriveDownload className="h-4 w-4" />}
              {busy ? "Importing…" : `Import "${path[path.length - 1]?.name || "folder"}"`}
            </button>
          </div>
          <p className="mt-3 text-[11.5px] text-ink-muted">
            Supported files in nested folders are included. Google Docs, Sheets and Slides are exported as Word, Excel and PowerPoint.
          </p>
        </>
      )}
    </Modal>
  );
}
