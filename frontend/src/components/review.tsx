import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, MessageSquareWarning, RotateCcw, Trash2, UserRound } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ago, STAGES } from "../lib/format";
import { Spinner, useToast } from "./ui";

export const ROLE_NAME: Record<string, string> = { admin: "Admin", presales: "Presales", architect: "Architect", finance: "Finance", delivery: "Delivery", viewer: "Viewer" };
const stageLabel = (k: string) => STAGES.find((s) => s.key === k)?.label || k;

/** "Owner: Priya" shown beside a deal name. */
export function OwnerTag({ owner, className }: { owner?: { name: string } | null; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full bg-brand-50 border border-brand-100 px-2 py-[1px] text-[11.5px] font-medium text-brand-800 whitespace-nowrap align-middle", className)}
      title="Deal owner">
      <UserRound className="h-3 w-3" aria-hidden /> {owner ? owner.name : "No owner"}
    </span>
  );
}

/** The lines of a stage a reviewer can pin a note to. Keys stay stable when the stage is re-run with the same content. */
export function stageLines(stage: string, data: any, reqs: any[] | undefined): { group: string; key: string; label: string }[] {
  const out: { group: string; key: string; label: string }[] = [];
  const add = (group: string, key: string, label: string) => label && out.push({ group, key, label: label.length > 140 ? label.slice(0, 137) + "…" : label });
  const d = data || {};
  if (["requirements", "matching", "gaps", "proposal"].includes(stage)) {
    let list = reqs || [];
    if (stage === "gaps") list = list.filter((r) => r.match_status === "gap" || r.match_status === "partial");
    list.forEach((r) => add("Requirements", `req:${r.id}`, `${r.source_ref || r.code} · ${r.text}`));
  } else if (stage === "architecture") {
    (d.layers || []).forEach((l: any) => (l.components || []).forEach((c: any) => add("Components", `comp:${l.layer}:${c.name}`, `${l.layer} · ${c.name}`)));
    (d.choices || []).forEach((c: any) => add("Technology decisions", `choice:${c.area}`, `${c.area}: ${c.choice}`));
  } else if (stage === "estimation") {
    (d.phases || []).forEach((p: any) => add("Phases", `phase:${p.name}`, p.name));
    (d.team || []).forEach((t: any, i: number) => add("Team", `team:${i}:${t.role}`, `${t.role}${t.phase ? ` (${t.phase})` : ""} · ${t.fte} FTE · ${t.location}`));
    (d.workstreams || []).forEach((w: any) => add("Workstreams", `ws:${w.name}`, `${w.name} · ${Math.round(w.effort_days)} person-days`));
    (d.assumptions || []).forEach((a: string, i: number) => add("Assumptions", `assume:${i}`, a));
  } else if (stage === "pricing") {
    (d.scenarios || []).forEach((s: any) => add("Price options", `scenario:${s.name}`, `${s.name} price`));
    (d.lines || []).forEach((l: any, i: number) => add("Cost by role", `line:${i}:${l.role}`, `${l.role}${l.phase ? ` (${l.phase})` : ""} · ${l.location}`));
    [["travel", "Travel and living"], ["contingency", "Contingency"]].forEach(([k, l]) => add("Cost by role", `cost:${k}`, l));
    (d.milestones || []).forEach((m: any) => add("Payment milestones", `milestone:${m.name}`, `${m.name} · ${m.pct}%`));
    (d.assumptions || []).forEach((a: string, i: number) => add("Assumptions", `assume:${i}`, a));
  } else if (stage === "handoff") {
    (d.scope || []).forEach((s: any) => add("Scope", `scope:${s.workstream}`, s.workstream));
    (d.risks || []).forEach((r: any) => add("Risks", `risk:${r.code}`, `${r.ref || r.code} · ${r.risk}`));
    (d.open_items || []).forEach((o: string, i: number) => add("Open items", `open:${i}`, o));
    (d.first_30_days || []).forEach((o: string, i: number) => add("First 30 days", `d30:${i}`, o));
  }
  return out;
}

function Note({ n, dealId }: { n: any; dealId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const act = useMutation({
    mutationFn: (what: "resolve" | "reopen" | "delete") => (what === "delete" ? api.del(`/deals/${dealId}/notes/${n.id}`) : api.post(`/deals/${dealId}/notes/${n.id}/${what}`)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["notes", dealId] }); qc.invalidateQueries({ queryKey: ["deal", dealId] }); },
    onError: (e: any) => toast("error", e.message),
  });
  const open = n.status === "open";
  return (
    <li className={clsx("rounded-xl border px-4 py-3", open ? "border-ember-400/40 bg-ember-50/40" : "border-line-soft bg-white opacity-75")}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-muted">
        <span className="font-semibold text-ink">{n.author}</span>
        {n.author_role && <span className="chip bg-white border border-line">{ROLE_NAME[n.author_role] || n.author_role}</span>}
        <span>{ago(n.created_at)}</span>
        {!open && <span className="text-ok font-semibold inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> Resolved by {n.resolved_by}</span>}
      </div>
      {n.line && <div className="mt-1.5 text-[12px] font-medium text-brand-800 bg-brand-50 border border-brand-100 rounded-md px-2 py-1 inline-block max-w-full truncate" title={n.line}>About: {n.line}</div>}
      <div className={clsx("mt-1.5 text-[13.5px] whitespace-pre-wrap", !open && "line-through decoration-ink-faint")}>{n.text}</div>
      <div className="mt-2 flex flex-wrap gap-1">
        {open && n.can_resolve && <button className="btn-ghost py-1 text-[12.5px]" disabled={act.isPending} onClick={() => act.mutate("resolve")}><CheckCircle2 className="h-3.5 w-3.5" /> Mark fixed</button>}
        {!open && n.can_resolve && <button className="btn-ghost py-1 text-[12.5px]" disabled={act.isPending} onClick={() => act.mutate("reopen")}><RotateCcw className="h-3.5 w-3.5" /> Reopen</button>}
        {n.mine && <button className="btn-ghost py-1 text-[12.5px] text-ink-muted" disabled={act.isPending} onClick={() => confirm("Delete this note?") && act.mutate("delete")}><Trash2 className="h-3.5 w-3.5" /> Delete</button>}
      </div>
    </li>
  );
}

/** Review notes for one stage: reviewers pin a note to a line; the owner fixes it and marks it fixed. */
export function ReviewNotes({ deal, stage }: { deal: any; stage: string }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: notes = [], isLoading } = useQuery({ queryKey: ["notes", deal.id, stage], queryFn: () => api.get<any[]>(`/deals/${deal.id}/notes?stage=${stage}`) });
  const { data: st } = useQuery({ queryKey: ["stage", deal.id, stage], queryFn: () => api.get(`/deals/${deal.id}/stages/${stage}`) });
  const needsReqs = ["requirements", "matching", "gaps", "proposal"].includes(stage);
  const { data: reqs } = useQuery({ queryKey: ["reqs", deal.id], queryFn: () => api.get<any[]>(`/deals/${deal.id}/requirements`), enabled: needsReqs });
  const lines = useMemo(() => stageLines(stage, (st as any)?.data, reqs), [stage, st, reqs]);
  const groups = useMemo(() => Array.from(new Set(lines.map((l) => l.group))), [lines]);
  const [show, setShow] = useState(false);
  const [lineKey, setLineKey] = useState("");
  const [text, setText] = useState("");
  const [showResolved, setShowResolved] = useState(false);
  const add = useMutation({
    mutationFn: () => api.post(`/deals/${deal.id}/stages/${stage}/notes`, { text, line_key: lineKey, line: lines.find((l) => l.key === lineKey)?.label || "" }),
    onSuccess: () => { setText(""); setLineKey(""); qc.invalidateQueries({ queryKey: ["notes", deal.id] }); qc.invalidateQueries({ queryKey: ["deal", deal.id] }); toast("ok", deal.owner ? `Note added. ${deal.owner.name} will see it in the deal.` : "Note added."); },
    onError: (e: any) => toast("error", e.message),
  });
  const open = notes.filter((n) => n.status === "open");
  const resolved = notes.filter((n) => n.status !== "open");
  const canWrite = user && user.role !== "viewer";
  const expanded = show || open.length > 0;
  return (
    <section className="card p-4 mb-4" aria-label="Review notes">
      <div className="flex flex-wrap items-center gap-3">
        <MessageSquareWarning className={clsx("h-[18px] w-[18px]", open.length ? "text-ember-600" : "text-ink-muted")} />
        <div className="font-bold text-[14px]">Review notes</div>
        <span className={clsx("chip", open.length ? "bg-ember-100 text-ember-600" : "bg-paper text-ink-muted")}>{open.length ? `${open.length} to fix` : "Nothing to fix"}</span>
        {resolved.length > 0 && <button className="text-[12.5px] text-ink-muted hover:text-ink" onClick={() => setShowResolved(!showResolved)}>{showResolved ? "Hide" : "Show"} {resolved.length} fixed</button>}
        <div className="flex-1" />
        {canWrite && !show && <button className="btn-outline py-1.5 text-[13px]" onClick={() => setShow(true)}>Add a note</button>}
      </div>
      {isLoading && <div className="py-3"><Spinner /></div>}
      {expanded && (open.length > 0 || (showResolved && resolved.length > 0)) && (
        <ul className="mt-3 space-y-2">
          {open.map((n) => <Note key={n.id} n={n} dealId={deal.id} />)}
          {showResolved && resolved.map((n) => <Note key={n.id} n={n} dealId={deal.id} />)}
        </ul>
      )}
      {!expanded && showResolved && <ul className="mt-3 space-y-2">{resolved.map((n) => <Note key={n.id} n={n} dealId={deal.id} />)}</ul>}
      {canWrite && show && (
        <form className="mt-3 grid gap-2 rounded-xl bg-paper p-3" onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate(); }}>
          <label className="label mb-0" htmlFor="note-line">Which line is it about?</label>
          <select id="note-line" className="input" value={lineKey} onChange={(e) => setLineKey(e.target.value)}>
            <option value="">The whole stage</option>
            {groups.map((g) => (
              <optgroup key={g} label={g}>{lines.filter((l) => l.group === g).map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}</optgroup>
            ))}
          </select>
          <textarea className="input h-20 py-2" maxLength={4000} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={`What needs to change? e.g. "Day rate is below our floor for this role." Type @name to tell a colleague.`} />
          <div className="flex items-center gap-2">
            <button className="btn-primary" disabled={!text.trim() || add.isPending}>{add.isPending ? <Spinner /> : null} Add note</button>
            <button type="button" className="btn-ghost" onClick={() => { setShow(false); setText(""); }}>Cancel</button>
            <span className="text-[12px] text-ink-muted ml-auto">{deal.owner ? `${deal.owner.name} owns this deal and will fix it.` : "This deal has no owner yet."}</span>
          </div>
        </form>
      )}
    </section>
  );
}

/** Every open note on the deal, grouped by stage: the owner's list of what's left to fix. */
export function LeftToFix({ deal }: { deal: any }) {
  const { data: notes = [] } = useQuery({ queryKey: ["notes", deal.id, "all"], queryFn: () => api.get<any[]>(`/deals/${deal.id}/notes`), enabled: deal.open_notes > 0 });
  const open = notes.filter((n) => n.status === "open");
  if (!deal.open_notes || !open.length) return null;
  const by = STAGES.map((s) => [s, open.filter((n) => n.stage === s.key)] as const).filter(([, l]) => l.length);
  return (
    <section className="card p-5 mb-5 border-ember-400/40">
      <div className="flex items-center gap-2"><MessageSquareWarning className="h-5 w-5 text-ember-600" /><div className="font-bold">What's left to fix</div>
        <span className="chip bg-ember-100 text-ember-600">{open.length} open note{open.length > 1 ? "s" : ""}</span></div>
      <div className="mt-3 grid md:grid-cols-2 gap-3">
        {by.map(([s, l]) => (
          <Link key={s.key} to={`/app/deals/${deal.id}/${s.key}`} className="rounded-xl border border-line-soft hover:border-brand-200 hover:bg-paper p-3 block">
            <div className="font-semibold text-[13.5px]">{stageLabel(s.key)} <span className="text-ink-muted font-normal">· {l.length}</span></div>
            <ul className="mt-1 space-y-1 text-[12.5px] text-ink-soft">
              {l.slice(0, 3).map((n) => <li key={n.id} className="line-clamp-1"><b className="font-medium text-ink">{n.author.split(" ")[0]}:</b> {n.line ? `[${n.line.slice(0, 40)}] ` : ""}{n.text}</li>)}
              {l.length > 3 && <li className="text-ink-muted">and {l.length - 3} more</li>}
            </ul>
          </Link>
        ))}
      </div>
    </section>
  );
}

/** Owner line in the deal header, with a picker for the owner or an admin to hand the deal over. */
export function OwnerPicker({ deal }: { deal: any }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const canChange = user && (user.role === "admin" || (deal.owner?.id === user.id && user.role === "presales"));
  const [editing, setEditing] = useState(false);
  const { data: people = [] } = useQuery({ queryKey: ["users"], queryFn: () => api.get<any[]>("/auth/users"), enabled: editing });
  const set = useMutation({
    mutationFn: (owner_id: string) => api.patch(`/deals/${deal.id}`, { owner_id }),
    onSuccess: (r: any) => { qc.invalidateQueries({ queryKey: ["deal", deal.id] }); qc.invalidateQueries({ queryKey: ["deals"] }); setEditing(false); toast("ok", `${r.owner?.name} now owns this deal.`); },
    onError: (e: any) => toast("error", e.message),
  });
  if (editing) {
    return (
      <select autoFocus className="input py-0.5 h-7 text-[12.5px] w-auto" defaultValue={deal.owner?.id || ""} disabled={set.isPending}
        onChange={(e) => e.target.value && e.target.value !== deal.owner?.id && set.mutate(e.target.value)} onBlur={() => !set.isPending && setEditing(false)}>
        {!deal.owner && <option value="">Pick an owner</option>}
        {people.filter((p) => p.active !== false && p.role !== "viewer").map((p) => <option key={p.id} value={p.id}>{p.name} · {ROLE_NAME[p.role] || p.role}</option>)}
      </select>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-ink-muted">Owner</span> <OwnerTag owner={deal.owner} />
      {canChange && <button className="text-[12px] text-brand-700 hover:underline" onClick={() => setEditing(true)}>Change</button>}
    </span>
  );
}

/** "Due 30 Nov 2026" in the deal header; presales people and admins can set or correct it (read from the RFP otherwise). */
export function DueDate({ deal }: { deal: any }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const canEdit = user && (user.role === "admin" || user.role === "presales");
  const set = useMutation({
    mutationFn: (due_date: string) => api.patch(`/deals/${deal.id}`, { due_date }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["deal", deal.id] }); qc.invalidateQueries({ queryKey: ["calendar"] }); setEditing(false); toast("ok", "Due date saved. It's on the calendar."); },
    onError: (e: any) => toast("error", e.message),
  });
  const isoGuess = /^\d{4}-\d{2}-\d{2}$/.test(deal.due_date || "") ? deal.due_date : "";
  if (editing) {
    return (
      <input type="date" autoFocus className="input py-0.5 h-7 text-[12.5px] w-auto" defaultValue={isoGuess} disabled={set.isPending}
        onChange={(e) => e.target.value && set.mutate(e.target.value)} onBlur={() => !set.isPending && setEditing(false)} aria-label="Due date" />
    );
  }
  const shown = isoGuess ? new Date(isoGuess + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : deal.due_date;
  return (
    <span className="inline-flex items-center gap-1.5">
      {shown ? <span>Due {shown}</span> : <span className="text-ink-faint">No due date</span>}
      {canEdit && <button className="text-[12px] text-brand-700 hover:underline" onClick={() => setEditing(true)}>{shown ? "Change" : "Set"}</button>}
    </span>
  );
}
