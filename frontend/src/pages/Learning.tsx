import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BookMarked, Brain, Gauge, RefreshCw, Search, Sparkles, Trash2, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Empty, Modal, PageLoader, Spinner, Stat, useToast } from "../components/ui";
import { api } from "../lib/api";
import { ago } from "../lib/format";

const KIND_LABEL: Record<string, string> = {
  category: "Category", subcategory: "Subcategory", priority: "Priority", match: "Capability match", response: "Proposal answer",
  added: "Missed requirement", removed: "Not a requirement",
};

function AccuracyChart({ rows }: { rows: any[] }) {
  const pts = rows.filter((r) => r.accuracy != null);
  if (pts.length < 1) return <div className="text-sm text-ink-muted py-8 text-center">Review requirements in a deal to start the accuracy trend.</div>;
  const W = 560, H = 180, P = 28;
  const x = (i: number) => P + (pts.length === 1 ? (W - 2 * P) / 2 : (i * (W - 2 * P)) / (pts.length - 1));
  const y = (v: number) => H - P - ((v - 50) / 50) * (H - 2 * P);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Classification accuracy per deal">
      {[50, 75, 100].map((g) => (
        <g key={g}>
          <line x1={P} x2={W - P} y1={y(g)} y2={y(g)} stroke="#E8EDF0" />
          <text x={4} y={y(g) + 4} fontSize="10" fill="#8A99A3">{g}%</text>
        </g>
      ))}
      <line x1={P} x2={W - P} y1={y(95)} y2={y(95)} stroke="#F5833A" strokeDasharray="4 4" />
      <text x={W - P} y={y(95) - 5} fontSize="10" fill="#DD6A22" textAnchor="end">95% target</text>
      <polyline fill="none" stroke="#118AC3" strokeWidth="2" points={pts.map((p, i) => `${x(i)},${y(Math.max(50, p.accuracy))}`).join(" ")} />
      {pts.map((p, i) => (
        <g key={p.deal_id}>
          <circle cx={x(i)} cy={y(Math.max(50, p.accuracy))} r="5" fill="#118AC3" stroke="#fff" strokeWidth="2"><title>{`${p.name}: ${p.accuracy}% (${p.reviewed} reviewed)`}</title></circle>
          <text x={x(i)} y={H - 8} fontSize="10" fill="#5F707B" textAnchor="middle">Deal {i + 1}</text>
        </g>
      ))}
    </svg>
  );
}

export default function Learning() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({ queryKey: ["learning"], queryFn: () => api.get("/learning") });
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<any>(null);
  const retrain = useMutation({
    mutationFn: () => api.post("/learning/retrain"),
    onSuccess: (m) => { qc.invalidateQueries({ queryKey: ["learning"] }); toast("ok", m.status === "trained" ? `Model retrained on ${m.examples} examples (${m.cv_accuracy ?? "—"}% accuracy).` : `Needs ${m.needed} reviewed requirements; has ${m.examples}.`); },
    onError: (e: any) => toast("error", e.message),
  });
  const save = useMutation({
    mutationFn: (e: any) => api.put(`/learning/answers/${e.id}`, { answer: e.answer }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["learning"] }); setEdit(null); toast("ok", "Answer saved to the library."); },
  });
  const del = useMutation({ mutationFn: (id: string) => api.del(`/learning/answers/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["learning"] }) });
  if (isLoading || !data) return <PageLoader />;
  const c = data.classifier;
  const lib = data.library;
  const answers = lib.top.filter((a: any) => !q || `${a.question} ${a.answer}`.toLowerCase().includes(q.toLowerCase()));
  const timeline = data.timeline;
  const lastReuse = [...timeline].reverse().find((t: any) => t.library_reuse_pct != null)?.library_reuse_pct;

  return (
    <div className="px-4 lg:px-8 py-6 max-w-[1400px] space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">AI learning</h1>
          <p className="text-ink-muted text-sm mt-0.5 max-w-3xl">What RevenueForge has learned from your team. Every correction, approved answer and deal outcome makes the next deal sharper, and none of it is shared with other companies.</p>
        </div>
        <div className="flex-1" />
        <span className={clsx("chip h-7 px-2.5", data.ai.enabled ? "bg-ok-bg text-ok" : "bg-line-soft text-ink-muted")}>
          {data.ai.enabled ? `AI engine: ${data.ai.provider} · ${data.ai.model}` : "AI engine off: rules engine only"}
        </span>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <Stat label="Corrections learned" value={data.corrections.total} sub="Fed back into every new AI run" tone="brand" />
        <Stat label="Your classifier" value={c.status === "trained" ? `${c.cv_accuracy ?? "—"}%` : `${c.examples}/${c.needed}`}
          sub={c.status === "trained" ? `Trained on ${c.examples} reviewed requirements` : "Reviewed requirements needed to train"} />
        <Stat label="Answer library" value={lib.size} sub={`${lib.uses} reuses · ${lib.won} from won deals`} />
        <Stat label="Answers reused, latest deal" value={lastReuse != null ? `${lastReuse}%` : "—"} sub="Less drafting, more consistency" tone="ember" />
      </div>

      <div className="grid lg:grid-cols-[1.4fr_1fr] gap-4">
        <section className="card p-5">
          <div className="flex items-center gap-2"><TrendingUp className="h-4 w-4 text-brand-600" /><h2 className="font-bold">Classification accuracy, deal by deal</h2></div>
          <p className="text-[12.5px] text-ink-muted mt-0.5 mb-3">Share of reviewed requirements whose category the AI got right. Corrections and your trained model push this up over time.</p>
          <AccuracyChart rows={timeline} />
          {timeline.length > 0 && <div className="mt-3 overflow-x-auto">
            <table className="w-full text-[12.5px] min-w-[480px]">
              <thead><tr className="text-ink-muted text-left"><th className="py-1 font-semibold">Deal</th><th className="py-1 font-semibold text-right">Reqs</th><th className="py-1 font-semibold text-right">Reviewed</th><th className="py-1 font-semibold text-right">Accuracy</th><th className="py-1 font-semibold text-right">Answers reused</th></tr></thead>
              <tbody>{timeline.map((t: any, i: number) => (
                <tr key={t.deal_id} className="border-t border-line-soft"><td className="py-1.5">Deal {i + 1} · {t.name}</td><td className="text-right num">{t.requirements}</td><td className="text-right num">{t.reviewed}</td>
                  <td className="text-right num font-semibold">{t.accuracy != null ? `${t.accuracy}%` : "—"}</td><td className="text-right num">{t.library_reuse_pct != null ? `${t.library_reuse_pct}%` : "—"}</td></tr>
              ))}</tbody>
            </table>
          </div>}
        </section>

        <section className="space-y-4">
          <div className="card p-5">
            <div className="flex items-center gap-2"><Brain className="h-4 w-4 text-brand-600" /><h2 className="font-bold">Your company's classifier</h2></div>
            <p className="text-[12.5px] text-ink-muted mt-1">A model trained only on your reviewed requirements. It retrains whenever requirements are approved or deals close, and overrides generic AI judgement when it is confident.</p>
            <div className="mt-3 text-[13px] space-y-1">
              <div className="flex justify-between"><span className="text-ink-soft">Status</span><span className="font-semibold capitalize">{c.status}</span></div>
              <div className="flex justify-between"><span className="text-ink-soft">Training examples</span><span className="num">{c.examples}</span></div>
              {c.trained_at && <div className="flex justify-between"><span className="text-ink-soft">Last trained</span><span>{ago(c.trained_at)}</span></div>}
              {c.classes && <div className="text-ink-muted text-[12px] pt-1">{Object.entries(c.classes).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>}
            </div>
            <button className="btn-outline mt-4" onClick={() => retrain.mutate()} disabled={retrain.isPending}>{retrain.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Retrain now</button>
          </div>
          <div className="card p-5">
            <div className="flex items-center gap-2"><Gauge className="h-4 w-4 text-brand-600" /><h2 className="font-bold">Estimate calibration</h2></div>
            <p className="text-[12.5px] text-ink-muted mt-1">When a won deal is delivered, record its actual effort (Outcome → Won). Future estimates are scaled by how your actuals compare with plans.</p>
            <div className="mt-3 flex items-baseline gap-2"><span className="num text-[26px] font-bold">×{data.calibration.factor}</span><span className="text-[12.5px] text-ink-muted">from {data.calibration.deals} delivered deal(s)</span></div>
            {data.pricing.bands.length > 0 && (
              <div className="mt-4 text-[12.5px]">
                <div className="font-semibold mb-1">Win rate by margin</div>
                {data.pricing.bands.map((b: any) => <div key={b.band} className="flex justify-between"><span>{b.band}</span><span className="num">{b.win_rate}% ({b.won}/{b.won + b.lost})</span></div>)}
              </div>
            )}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="px-5 py-3.5 border-b border-line flex items-center gap-2"><Sparkles className="h-4 w-4 text-ember-500" /><h2 className="font-bold">Recent corrections</h2>
          <span className="text-[12.5px] text-ink-muted ml-2">{Object.entries(data.corrections.by_kind).map(([k, v]) => `${KIND_LABEL[k] || k} ${v}`).join(" · ")}</span></div>
        {data.corrections.recent.length === 0 ? <Empty title="No corrections yet">Change a category, override a match or rewrite an answer in any deal, and it shows up here.</Empty> : (
          <ul className="divide-y divide-line-soft">
            {data.corrections.recent.map((e: any, i: number) => (
              <li key={i} className="px-5 py-3 grid md:grid-cols-[150px_1fr_auto] gap-x-4 gap-y-1 text-[13px]">
                <span className="chip bg-brand-50 text-brand-700 h-fit w-fit">{KIND_LABEL[e.kind] || e.kind}</span>
                <div className="min-w-0">
                  <div className="line-clamp-1 text-ink">{e.text}</div>
                  <div className="text-ink-muted text-[12.5px] line-clamp-2">{e.kind === "response" ? `Rewritten: “${e.human}”` : `${e.ai || "—"} → ${e.human}`}</div>
                </div>
                <span className="text-[12px] text-ink-muted whitespace-nowrap">{e.user} · {ago(e.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <div className="px-5 py-3 border-b border-line flex flex-wrap items-center gap-3">
          <BookMarked className="h-4 w-4 text-brand-600" /><h2 className="font-bold">Answer library</h2>
          <span className="text-[12.5px] text-ink-muted">Approved answers, reused automatically on similar requirements. Won deals rank higher.</span>
          <div className="flex-1" />
          <div className="relative w-full sm:w-64"><Search className="h-4 w-4 absolute left-2.5 top-2.5 text-ink-faint" /><input className="input h-9 pl-8" placeholder="Search answers" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        </div>
        {answers.length === 0 ? <Empty title="The library is empty">Approve a deal's proposal stage and its answers are added here.</Empty> : (
          <ul className="divide-y divide-line-soft max-h-[560px] overflow-auto scroll-thin">
            {answers.map((a: any) => (
              <li key={a.id} className="px-5 py-3.5 grid lg:grid-cols-[1fr_1.4fr_auto] gap-4 group">
                <div className="text-[13px] text-ink-soft"><div className="line-clamp-3">{a.question}</div><div className="text-[11.5px] text-ink-faint mt-1">{a.source}</div></div>
                <div className="text-[13.5px] leading-snug">{a.answer}</div>
                <div className="flex lg:flex-col items-start gap-1.5 text-[11.5px]">
                  <span className={clsx("chip", a.outcome === "won" ? "bg-ok-bg text-ok" : a.outcome === "lost" ? "bg-[#FBE7E5] text-fit-gap-ink" : "bg-line-soft text-ink-muted")}>{a.outcome === "pending" ? "Pending" : a.outcome === "won" ? "From a win" : "From a loss"}</span>
                  <span className="chip bg-paper border border-line text-ink-soft">{a.origin === "human" ? "Team-written" : "AI, approved"}</span>
                  <span className="num text-ink-muted">Used {a.uses}×</span>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                    <button className="btn-ghost h-7 px-2 text-[12px]" onClick={() => setEdit({ ...a })}>Edit</button>
                    <button className="btn-ghost h-7 px-2 text-fit-gap-ink" aria-label="Delete answer" onClick={() => confirm("Remove this answer from the library?") && del.mutate(a.id)}><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Modal open={!!edit} onClose={() => setEdit(null)} title="Edit library answer" wide>
        {edit && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(edit); }}>
            <div className="text-[13px] text-ink-soft bg-paper rounded p-3">{edit.question}</div>
            <textarea className="input h-40 py-2" value={edit.answer} onChange={(e) => setEdit({ ...edit, answer: e.target.value })} />
            <div className="text-[12px] text-ink-muted">Use {"{{CLIENT}}"} where the client's name (or alias) should appear.</div>
            <button className="btn-primary" disabled={save.isPending}>Save answer</button>
          </form>
        )}
      </Modal>
    </div>
  );
}
