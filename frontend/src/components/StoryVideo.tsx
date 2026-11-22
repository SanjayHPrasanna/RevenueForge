import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, Clapperboard, Download, RefreshCw, Volume2, VolumeX } from "lucide-react";
import { useEffect, useState } from "react";
import { api, download, getToken } from "../lib/api";
import { Spinner, useToast } from "./ui";

export type StoryStatus = {
  status: "none" | "running" | "ready" | "failed";
  pct?: number; message?: string; duration?: number; voice?: boolean; engine?: string; error?: string;
  created_at?: string; stale?: boolean; size?: number; can_make?: boolean; has_client_name?: boolean; use_client_name?: boolean;
};

export function useStory(dealId: string) {
  return useQuery({
    queryKey: ["story", dealId],
    queryFn: () => api.get<StoryStatus>(`/deals/${dealId}/story`),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false),
  });
}

/** Plays the MP4 (fetched with the sign-in token, since a <video> tag can't send it). */
function Player({ dealId, stamp }: { dealId: string; stamp?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true, made: string | null = null;
    const token = getToken();
    fetch(`/api/deals/${dealId}/download/story`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(async (r) => { if (!r.ok) throw new Error("Couldn't load the video."); return r.blob(); })
      .then((b) => { if (!alive) return; made = URL.createObjectURL(b); setUrl(made); })
      .catch((e) => alive && setErr(e.message));
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [dealId, stamp]);
  if (err) return <div className="aspect-video grid place-items-center rounded-lg bg-paper text-[13px] text-fit-gap-ink">{err}</div>;
  if (!url) return <div className="aspect-video grid place-items-center rounded-lg bg-brand-500"><Spinner className="h-6 w-6 text-white" /></div>;
  return <video src={url} controls preload="metadata" className="w-full aspect-video rounded-lg bg-brand-500 shadow-card" />;
}

export default function StoryVideo({ dealId }: { dealId: string }) {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: s } = useStory(dealId);
  const [useName, setUseName] = useState(true);
  useEffect(() => { if (s?.use_client_name === false) setUseName(false); }, [s?.use_client_name]);
  const make = useMutation({
    mutationFn: () => api.post(`/deals/${dealId}/story`, { use_client_name: useName }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["story", dealId] }),
    onError: (e: any) => toast("error", e.message),
  });
  if (!s) return null;
  const running = s.status === "running" || make.isPending;
  const mins = s.duration ? `${Math.floor(s.duration / 60)}:${String(Math.round(s.duration % 60)).padStart(2, "0")}` : "";

  return (
    <div className="card p-5 md:p-6">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="flex-1 min-w-[260px]">
          <div className="flex items-center gap-2 font-bold"><Clapperboard className="h-4 w-4 text-brand-600" /> Solution video</div>
          <p className="text-[13.5px] text-ink-soft mt-1 max-w-2xl">
            A short narrated video of your solution, team, proof and delivery plan, made only from this deal's data.
            Send it with the proposal to help the client picture the work. Costs, margins and internal notes never appear in it.
          </p>
        </div>
        {s.status === "ready" && !running && (
          <div className="flex flex-wrap gap-2">
            <button className="btn-outline" onClick={() => download(`/deals/${dealId}/download/story`, "solution video.mp4").catch((e) => toast("error", e.message))}>
              <Download className="h-4 w-4" /> Video .mp4
            </button>
            <button className="btn-ghost" onClick={() => make.mutate()}><RefreshCw className="h-4 w-4" /> Make again</button>
          </div>
        )}
      </div>

      {s.can_make === false && s.status !== "ready" ? (
        <div className="mt-4 text-[13px] text-ink-muted">Available once the deal has been run up to Estimation.</div>
      ) : running ? (
        <div className="mt-5 max-w-xl">
          <div className="flex items-center gap-2 text-[13.5px] font-medium"><Spinner className="h-4 w-4 text-brand-500" /> {s.message || "Starting"}…</div>
          <div className="mt-2.5 h-2 rounded-full bg-line overflow-hidden"><div className="h-full bg-brand-500 transition-all duration-700" style={{ width: `${Math.max(3, s.pct || 0)}%` }} /></div>
          <div className="mt-2 text-[12px] text-ink-muted">Usually under two minutes. You can keep working; it carries on in the background.</div>
        </div>
      ) : s.status === "ready" ? (
        <div className="mt-5 grid lg:grid-cols-[minmax(0,720px)_1fr] gap-5 items-start">
          <Player dealId={dealId} stamp={s.created_at} />
          <div className="space-y-3 text-[13px]">
            {s.stale && (
              <div className="rounded-lg bg-fit-partial-soft text-fit-partial-ink px-3 py-2.5 flex gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>The deal has changed since this video was made. <button className="font-semibold underline" onClick={() => make.mutate()}>Make it again</button> so it matches the proposal.</span>
              </div>
            )}
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
              <dt className="text-ink-muted">Length</dt><dd className="num font-medium">{mins}</dd>
              <dt className="text-ink-muted">Voice</dt>
              <dd className="font-medium flex items-center gap-1.5">{s.voice ? <><Volume2 className="h-3.5 w-3.5" /> Spoken narration with captions</> : <><VolumeX className="h-3.5 w-3.5" /> Captions only (no computer voice found)</>}</dd>
              <dt className="text-ink-muted">Script</dt><dd className="font-medium">{s.engine === "ai" ? "Written by AI from the deal's facts" : "Standard wording (AI not available)"}</dd>
              <dt className="text-ink-muted">Client name</dt><dd className="font-medium">{s.use_client_name !== false && s.has_client_name ? "Says the client's real name" : `Says "you"`}</dd>
            </dl>
            <p className="text-[12px] text-ink-muted">Watch it through before sending. Choose "Proposal + video" when you download the proposal to send both together.</p>
          </div>
        </div>
      ) : (
        <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">
          <button className="btn-primary" disabled={make.isPending} onClick={() => make.mutate()}><Clapperboard className="h-4 w-4" /> Make the video</button>
          {s.has_client_name && (
            <label className="inline-flex items-center gap-2 text-[13px] text-ink-soft cursor-pointer">
              <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={useName} onChange={(e) => setUseName(e.target.checked)} />
              Say the client's real name in the video (otherwise it says "you")
            </label>
          )}
          {s.status === "failed" && <div className="w-full text-[13px] text-fit-gap-ink">{s.error || "Making the video failed."} Try again.</div>}
          <div className="w-full text-[12px] text-ink-muted">The AI only sees the deal's facts with the client's name hidden; the name is added back on your computer.</div>
        </div>
      )}
    </div>
  );
}

/** Proposal download with a choice: the Word document alone, or the document and the video together. */
export function ProposalDownload({ dealId }: { dealId: string }) {
  const toast = useToast();
  const { data: s } = useStory(dealId);
  const [withVideo, setWithVideo] = useState(false);
  const ready = s?.status === "ready";
  const go = () =>
    download(`/deals/${dealId}/download/${withVideo ? "proposal_pack" : "proposal"}`, withVideo ? "proposal with video.zip" : "proposal.docx")
      .catch((e) => toast("error", e.message));
  return (
    <div className="mt-4">
      <div className="grid grid-cols-2 rounded-lg border border-line p-1 bg-paper text-[13px] font-semibold" role="radiogroup" aria-label="What to download">
        {[[false, "Proposal only"], [true, "Proposal + video"]].map(([v, l]) => (
          <button key={String(v)} role="radio" aria-checked={withVideo === v} onClick={() => setWithVideo(v as boolean)}
            className={clsx("h-8 rounded-md transition-colors", withVideo === v ? "bg-surface shadow-card text-brand-900" : "text-ink-muted hover:text-ink")}>{l as string}</button>
        ))}
      </div>
      {withVideo && !ready && <div className="text-[12px] text-fit-partial-ink mt-2">Make the solution video first (below the summary).</div>}
      {withVideo && ready && s?.stale && <div className="text-[12px] text-fit-partial-ink mt-2">The video is older than the latest changes. Consider making it again.</div>}
      <button className="btn-primary w-full mt-2.5" disabled={withVideo && !ready} onClick={go}>
        <Download className="h-4 w-4" /> {withVideo ? "Download .zip (Word + video)" : "Download .docx"}
      </button>
    </div>
  );
}
