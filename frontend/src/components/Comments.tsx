import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AtSign, MessageSquare, Send, Trash2 } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api } from "../lib/api";
import { Spinner, useToast } from "./ui";

type Comment = { id: string; author: string; text: string; created_at: string; mine: boolean };
type Person = { id: string; name: string; email: string; role: string; active: boolean };

function ago(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

const handle = (p: Person) => p.email.split("@")[0];

/** Text with @mentions picked out. Plain text only. */
function WithMentions({ text }: { text: string }) {
  return <>{text.split(/(@[A-Za-z0-9._-]{2,60})/g).map((part, i) => (part.startsWith("@") ? <span key={i} className="font-semibold text-brand-700">{part}</span> : part))}</>;
}

/** Discussion about one requirement. Mention a colleague with @ and they get an email. */
export function CommentsPanel({ dealId, req }: { dealId: string; req: any }) {
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["comments", dealId, req.id];
  const { data: comments, isLoading } = useQuery({ queryKey: key, queryFn: () => api.get<Comment[]>(`/deals/${dealId}/requirements/${req.id}/comments`) });
  const { data: people } = useQuery({ queryKey: ["users"], queryFn: () => api.get<Person[]>("/auth/users"), staleTime: 60_000 });
  const [text, setText] = useState("");
  const [caret, setCaret] = useState(0);
  const box = useRef<HTMLTextAreaElement>(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["reqs", dealId] });
  };
  const add = useMutation({
    mutationFn: () => api.post(`/deals/${dealId}/requirements/${req.id}/comments`, { text }),
    onSuccess: () => { setText(""); refresh(); },
    onError: (e: any) => toast("error", e.message),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/deals/${dealId}/comments/${id}`),
    onSuccess: refresh,
    onError: (e: any) => toast("error", e.message),
  });

  // @-suggestions for the word being typed
  const typing = useMemo(() => {
    const m = text.slice(0, caret).match(/@([A-Za-z0-9._-]*)$/);
    return m ? m[1].toLowerCase() : null;
  }, [text, caret]);
  const matches = typing === null ? [] : (people || []).filter((p) => p.active && `${p.name} ${p.email}`.toLowerCase().includes(typing)).slice(0, 5);
  const pick = (p: Person) => {
    const before = text.slice(0, caret).replace(/@([A-Za-z0-9._-]*)$/, `@${handle(p)} `);
    const next = before + text.slice(caret);
    setText(next);
    setCaret(before.length);
    requestAnimationFrame(() => { box.current?.focus(); box.current?.setSelectionRange(before.length, before.length); });
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (matches.length && (e.key === "Enter" || e.key === "Tab")) {
      e.preventDefault();
      pick(matches[0]);
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim()) {
      e.preventDefault();
      add.mutate();
    }
  };

  return (
    <div className="card flex flex-col max-h-[calc(100vh-120px)] lg:sticky lg:top-[72px]">
      <div className="flex-1 min-h-[160px] overflow-auto scroll-thin px-4 py-3 space-y-3">
        {isLoading && <div className="py-6 grid place-items-center"><Spinner /></div>}
        {comments?.length === 0 && (
          <div className="py-8 text-center text-[13px] text-ink-muted">
            <MessageSquare className="h-6 w-6 mx-auto mb-2 text-brand-300" />
            No discussion yet. Ask a question or leave a note for the team.<br />Type <span className="font-semibold text-brand-700">@</span> to mention someone; they’ll get an email.
          </div>
        )}
        {comments?.map((c) => (
          <div key={c.id} className="group flex gap-2.5 anim-fade-in">
            <span className="h-7 w-7 shrink-0 rounded-full bg-gradient-to-br from-brand-500 to-brand-900 text-white text-[11px] font-bold grid place-items-center">
              {c.author.split(" ").map((p) => p[0]).slice(0, 2).join("")}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2 text-[12px]">
                <span className="font-semibold text-ink">{c.author}</span>
                <span className="text-ink-faint">{ago(c.created_at)}</span>
                {c.mine && (
                  <button className="ml-auto opacity-0 group-hover:opacity-100 focus:opacity-100 text-ink-faint hover:text-fit-gap-ink" aria-label="Delete comment" onClick={() => del.mutate(c.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <div className="mt-0.5 rounded-[14px] rounded-tl-md bg-paper px-3 py-2 text-[13px] leading-relaxed text-ink whitespace-pre-wrap break-words"><WithMentions text={c.text} /></div>
            </div>
          </div>
        ))}
      </div>
      <div className="relative border-t border-line-soft p-3">
        {matches.length > 0 && (
          <ul className="absolute bottom-full left-3 right-3 mb-1 card shadow-lift py-1 text-[13px] anim-scale-in origin-bottom" role="listbox">
            {matches.map((p, i) => (
              <li key={p.id}>
                <button type="button" onMouseDown={(e) => { e.preventDefault(); pick(p); }}
                  className={clsx("w-full px-3 py-1.5 text-left flex items-center gap-2 hover:bg-paper", i === 0 && "bg-brand-50/60")}>
                  <AtSign className="h-3.5 w-3.5 text-brand-500" />
                  <span className="font-semibold">{p.name}</span>
                  <span className="text-ink-faint truncate">{handle(p)} · {p.role}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-paper px-3 py-2 transition-all focus-within:border-brand-400 focus-within:bg-white focus-within:ring-4 focus-within:ring-brand-500/10">
          <label className="sr-only" htmlFor={`c-${req.id}`}>Comment on {req.code}</label>
          <textarea id={`c-${req.id}`} ref={box} rows={2} value={text} placeholder={`Comment on ${req.source_ref || req.code}… (@ to mention)`}
            onChange={(e) => { setText(e.target.value); setCaret(e.target.selectionStart); }} onKeyUp={(e) => setCaret(e.currentTarget.selectionStart)}
            onClick={(e) => setCaret(e.currentTarget.selectionStart)} onKeyDown={onKey}
            className="min-h-[40px] max-h-40 flex-1 resize-y border-0 bg-transparent text-[13px] leading-relaxed focus:outline-none focus:ring-0" />
          <button className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-700 text-white transition-all hover:bg-brand-800 active:scale-95 disabled:bg-line"
            disabled={!text.trim() || add.isPending} onClick={() => add.mutate()} aria-label="Post comment">
            {add.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Send className="h-3.5 w-3.5" />}
          </button>
        </div>
        <div className="mt-1 text-[10.5px] text-ink-faint">Ctrl + Enter to post</div>
      </div>
    </div>
  );
}
