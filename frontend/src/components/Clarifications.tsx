import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Copy, Download, HelpCircle, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Spinner, useToast } from "./ui";

type Item = { code: string; question: string; why: string };
type Data = { items: Item[]; by: "ai" | "rules" | null; generated_at: string | null; edited_by?: string };

/** Questions to send the client before answering: drafted from vague, open-ended or missing-number requirements. */
export function Clarifications({ deal }: { deal: any }) {
  const { user } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const key = ["clarifications", deal.id];
  const { data } = useQuery({ queryKey: key, queryFn: () => api.get<Data>(`/deals/${deal.id}/clarifications`) });
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [dirty, setDirty] = useState(false);
  const canEdit = ["admin", "presales", "architect"].includes(user?.role || "");
  useEffect(() => { if (data && !dirty) setItems(data.items || []); }, [data]);

  const make = useMutation({
    mutationFn: () => api.post<Data>(`/deals/${deal.id}/clarifications`),
    onSuccess: (d) => { qc.setQueryData(key, d); setItems(d.items); setDirty(false); setOpen(true);
      toast("ok", d.items.length ? `${d.items.length} questions drafted${d.by === "rules" ? " (AI unavailable, so simple rules were used)" : ""}.` : "Nothing unclear found."); },
    onError: (e: any) => toast("error", e.message),
  });
  const save = useMutation({
    mutationFn: () => api.put<Data>(`/deals/${deal.id}/clarifications`, { items }),
    onSuccess: (d) => { qc.setQueryData(key, d); setDirty(false); toast("ok", "Questions saved."); },
    onError: (e: any) => toast("error", e.message),
  });
  const edit = (i: number, patch: Partial<Item>) => { setItems(items.map((x, j) => (j === i ? { ...x, ...patch } : x))); setDirty(true); };
  const asText = () => items.filter((i) => i.question.trim()).map((i, n) => `${n + 1}. ${i.code ? `[${i.code}] ` : ""}${i.question.trim()}`).join("\n\n");
  const copy = async () => {
    try { await navigator.clipboard.writeText(asText()); toast("ok", "Questions copied. Paste them into your email to the client."); }
    catch { toast("error", "Couldn't copy. Select the text and copy it instead."); }
  };
  const downloadTxt = () => {
    const blob = new Blob([`Clarification questions: ${deal.name}\n\n${asText()}\n`], { type: "text/plain" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${deal.name} - clarification questions.txt` });
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const n = items.length;

  return (
    <section className="card mb-4 overflow-hidden">
      <button className="w-full flex items-center gap-3 px-5 py-3.5 text-left hover:bg-paper/60 transition-colors" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="h-9 w-9 shrink-0 rounded-xl bg-gradient-to-b from-ember-50 to-white border border-ember-100 text-ember-600 grid place-items-center"><HelpCircle className="h-[18px] w-[18px]" /></span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-[14.5px]">Questions for the client</div>
          <div className="text-[12.5px] text-ink-muted">
            {n ? `${n} question${n === 1 ? "" : "s"} about vague, open-ended or missing details${data?.by === "ai" ? ", drafted by AI" : ""}. Review, edit and send before you answer.`
              : "Draft questions about vague or missing details, to send the client before you answer."}
          </div>
        </div>
        {n > 0 && <span className="chip bg-ember-50 text-ember-600 num">{n}</span>}
        <ChevronDown className={`h-4 w-4 text-ink-muted transition-transform duration-300 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="border-t border-line-soft px-5 py-4 anim-fade-in">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            {canEdit && (
              <button className={n ? "btn-outline h-9" : "btn-primary h-9"} onClick={() => make.mutate()} disabled={make.isPending || deal.status === "processing"}>
                {make.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />} {n ? "Draft again" : "Draft questions"}
              </button>
            )}
            {make.isPending && <span className="text-[12.5px] text-ink-muted">Reading every requirement… this can take up to a minute.</span>}
            <div className="flex-1" />
            {n > 0 && <>
              <button className="btn-ghost h-9" onClick={copy}><Copy className="h-4 w-4" /> Copy all</button>
              <button className="btn-ghost h-9" onClick={downloadTxt}><Download className="h-4 w-4" /> Download</button>
            </>}
            {canEdit && dirty && <button className="btn-primary h-9" onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending && <Spinner />} Save changes</button>}
          </div>
          {n === 0 && !make.isPending && <div className="text-[13px] text-ink-muted py-2">No questions yet.</div>}
          <ol className="space-y-2.5">
            {items.map((it, i) => (
              <li key={i} className="group flex gap-3 rounded-xl border border-line-soft bg-[#FBFCFD] px-3 py-2.5">
                <span className="num text-[12px] font-semibold text-ink-faint pt-1 w-5 text-right">{i + 1}.</span>
                <div className="min-w-0 flex-1">
                  {canEdit ? (
                    <textarea className="w-full resize-y border-0 bg-transparent p-0 text-[13.5px] leading-relaxed text-ink focus:outline-none focus:ring-0" rows={2}
                      value={it.question} onChange={(e) => edit(i, { question: e.target.value })} aria-label={`Question ${i + 1}`} />
                  ) : <div className="text-[13.5px] leading-relaxed">{it.question}</div>}
                  <div className="text-[11.5px] text-ink-muted mt-0.5">{it.code && <span className="font-semibold text-brand-700 mr-1.5">{it.code}</span>}{it.why}</div>
                </div>
                {canEdit && (
                  <button className="self-start opacity-0 group-hover:opacity-100 focus:opacity-100 text-ink-faint hover:text-fit-gap-ink p-1" aria-label={`Remove question ${i + 1}`}
                    onClick={() => { setItems(items.filter((_, j) => j !== i)); setDirty(true); }}><Trash2 className="h-4 w-4" /></button>
                )}
              </li>
            ))}
          </ol>
          {canEdit && n > 0 && (
            <button className="mt-3 text-[13px] font-semibold text-brand-700 inline-flex items-center gap-1 hover:underline"
              onClick={() => { setItems([...items, { code: "", question: "", why: "Added by the team" }]); setDirty(true); }}>
              <Plus className="h-3.5 w-3.5" /> Add a question
            </button>
          )}
        </div>
      )}
    </section>
  );
}
