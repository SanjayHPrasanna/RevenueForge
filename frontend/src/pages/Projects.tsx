import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, ArrowLeft, Briefcase, Building2, CalendarClock, Check, ChevronRight, FolderKanban, Pencil, Plus, Rocket, Trash2 } from "lucide-react";
import { ReactNode, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Empty, Modal, PageLoader, Spinner, StatStrip, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ago, ENGAGEMENT, money } from "../lib/format";
import { DealStatus } from "./Dashboard";

/* Delivery 360: a won bid becomes a project and is run to the end here. Client 360 shows every bid and project for one client. */

const EDIT_ROLES = ["admin", "presales", "delivery", "finance", "architect"];
const useCanEdit = () => EDIT_ROLES.includes(useAuth().user?.role || "");
const H1 = "font-display font-semibold text-[26px] md:text-[30px] leading-[1.05] tracking-[-0.025em] text-brand-950";
const day = (s?: string) => (s ? new Date(s + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const STATUS_LABEL: Record<string, string> = { planning: "Planning", active: "Active", on_hold: "On hold", completed: "Completed", cancelled: "Cancelled" };

export function Health({ h, reasons, big }: { h?: string | null; reasons?: string[]; big?: boolean }) {
  if (!h) return <span className="text-ink-faint text-[12.5px]">—</span>;
  const cls = h === "green" ? "bg-ok-bg text-ok" : h === "amber" ? "bg-fit-partial-soft text-fit-partial-ink" : h === "red" ? "bg-fit-gap-soft text-fit-gap-ink" : "bg-line-soft text-ink-muted";
  const dot = h === "green" ? "bg-ok" : h === "amber" ? "bg-fit-partial" : h === "red" ? "bg-fit-gap" : "bg-ink-faint";
  const label = h === "green" ? "On track" : h === "amber" ? "Needs attention" : h === "red" ? "At risk" : "Closed";
  return (
    <span className={clsx("chip", cls, big && "h-7 px-3 text-[12.5px]")} title={reasons?.length ? reasons.join("\n") : undefined}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", dot)} />{label}
    </span>
  );
}

function ProjectStatus({ s }: { s: string }) {
  const cls = s === "active" ? "bg-brand-500/10 text-brand-700" : s === "on_hold" ? "bg-ember-50 text-ember-600" : s === "completed" ? "bg-ok-bg text-ok" : "bg-line-soft text-ink-muted";
  return <span className={clsx("chip", cls)}>{STATUS_LABEL[s] || s}</span>;
}

/** Share of milestones done: a plain accent bar (low early progress isn't bad news, so no traffic-light colours). */
function Meter({ value, className }: { value: number; className?: string }) {
  return (
    <div className={clsx("h-1.5 rounded-full bg-line-soft overflow-hidden", className)} role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

const sumMoney = (m: Record<string, number> | undefined) => {
  const e = Object.entries(m || {}).filter(([, v]) => Math.abs(v) >= 0.5);
  if (!e.length) return Object.keys(m || {}).length ? money(0, Object.keys(m!)[0]) : "—";
  return e.map(([c, v]) => money(v, c)).join(" + ");
};

// ======================================================================= projects list
export function Projects() {
  const { data, isLoading } = useQuery({ queryKey: ["projects"], queryFn: () => api.get<any>("/projects") });
  const [creating, setCreating] = useState(false);
  const canEdit = useCanEdit();
  if (isLoading || !data) return <PageLoader />;
  const ps: any[] = data.projects;
  const live = ps.filter((p) => !["completed", "cancelled"].includes(p.status));
  const byCcy = (f: (p: any) => number) => {
    const out: Record<string, number> = {};
    live.forEach((p) => { out[p.currency || "?"] = (out[p.currency || "?"] || 0) + (f(p) || 0); });
    return out;
  };
  const atRisk = live.filter((p) => p.summary.health === "red").length;
  const attention = live.filter((p) => p.summary.health === "amber").length;
  return (
    <div className="px-4 lg:px-8 py-6 max-w-[1400px] space-y-5">
      <div className="flex items-center gap-3">
        <div>
          <h1 className={H1}>Projects</h1>
          <p className="text-[13.5px] text-ink-muted mt-1">Won bids, delivered to the end: plan, people, money, risks and service, with health worked out from the facts.</p>
        </div>
        <div className="flex-1" />
        {canEdit && <button className="btn-outline" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New project</button>}
      </div>
      {ps.length > 0 && <StatStrip items={[
        { label: "Live projects", value: live.length, sub: `${ps.length - live.length} closed` },
        { label: "Contract value (live)", value: sumMoney(byCcy((p) => p.summary.value_total)), sub: "incl. approved changes" },
        { label: "Outstanding", value: sumMoney(byCcy((p) => p.summary.outstanding)), sub: `overdue ${sumMoney(byCcy((p) => p.summary.overdue))}`, tone: live.some((p) => p.summary.overdue) ? "gap" : undefined },
        { label: "At risk / needs attention", value: `${atRisk} / ${attention}`, sub: "red / amber", tone: atRisk ? "gap" : undefined },
      ]} />}
      {data.ready.length > 0 && <ReadyToStart ready={data.ready} canEdit={canEdit} />}
      {!ps.length ? (
        <div className="card">
          <Empty icon={<FolderKanban className="h-8 w-8" />} title="No projects yet"
            action={data.ready.length ? undefined : <Link className="btn-primary" to="/app/deals">Go to deals</Link>}>
            When a deal is won, start its project here or from the deal page. The bid's plan, team, price and risks come with it.
          </Empty>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[980px]">
            <thead><tr>
              <th className="th">Project</th><th className="th">Status</th><th className="th">Health</th><th className="th w-[150px]">Milestones</th>
              <th className="th text-right">Value</th><th className="th text-right">Invoiced / paid</th><th className="th">Next milestone</th><th className="th">Manager</th>
            </tr></thead>
            <tbody>
              {ps.map((p) => {
                const s = p.summary;
                return (
                  <tr key={p.id} className="hover:bg-ink/[.02]">
                    <td className="td"><Link to={`/app/projects/${p.id}`} className="font-semibold hover:text-brand-700">{p.name}</Link>
                      <div className="text-[12.5px] text-ink-muted"><Link to={`/app/clients/${p.client_key}`} className="hover:underline">{p.client || "Client not named"}</Link>
                        {p.engagement_type ? ` · ${ENGAGEMENT[p.engagement_type] || p.engagement_type}` : ""}</div></td>
                    <td className="td"><ProjectStatus s={p.status} /></td>
                    <td className="td"><Health h={s.health} reasons={s.health_reasons} />
                      {s.health_reasons?.[0] && <div className="text-[11.5px] text-ink-muted mt-1 max-w-[220px] leading-snug">{s.health_reasons[0]}</div>}</td>
                    <td className="td">{s.progress_pct == null ? <span className="text-ink-faint">—</span> : <>
                      <div className="flex items-center gap-2"><Meter value={s.progress_pct} className="flex-1" /><span className="num text-[12px]">{s.progress_pct}%</span></div>
                      <div className="text-[11.5px] text-ink-muted mt-1">{s.milestones.done}/{s.milestones.total} done{s.milestones.late ? ` · ${s.milestones.late} late` : ""}{s.time_pct != null ? ` · ${s.time_pct}% of time` : ""}</div></>}</td>
                    <td className="td text-right num whitespace-nowrap">{money(s.value_total, p.currency)}</td>
                    <td className="td text-right num whitespace-nowrap">{money(s.invoiced, p.currency)}<div className="text-[11.5px] text-ink-muted">{money(s.paid, p.currency)} paid</div></td>
                    <td className="td text-[13px]">{s.next_milestone ? <><div className="truncate max-w-[200px]">{s.next_milestone.title}</div>
                      <div className={clsx("text-[11.5px]", s.next_milestone.late ? "text-fit-gap-ink font-semibold" : "text-ink-muted")}>{s.next_milestone.late ? "late · " : ""}{day(s.next_milestone.due_date)}</div></> : <span className="text-ink-faint">—</span>}</td>
                    <td className="td text-[13px]">{p.manager?.name || <span className="text-ink-faint">—</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <NewProject open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

function ReadyToStart({ ready, canEdit }: { ready: any[]; canEdit: boolean }) {
  const nav = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: (deal_id: string) => api.post<any>("/projects", { deal_id }),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["projects"] }); nav(`/app/projects/${p.id}`); },
    onError: (e: any) => toast("error", e.message),
  });
  return (
    <section className="card">
      <div className="px-5 py-3.5 border-b border-line-soft flex items-center gap-2">
        <Rocket className="h-4 w-4 text-brand-600" /><div className="font-bold flex-1">Won, ready to start</div>
        <span className="text-[12.5px] text-ink-muted">The bid's plan, team, price and gaps become the project's starting point</span>
      </div>
      <ul className="divide-y divide-line-soft">
        {ready.map((r) => (
          <li key={r.deal_id} className="px-5 py-3 flex flex-wrap items-center gap-3 text-[13.5px]">
            <div className="flex-1 min-w-[240px]"><Link to={`/app/deals/${r.deal_id}`} className="font-semibold hover:text-brand-700">{r.name}</Link>
              <div className="text-[12.5px] text-ink-muted">{r.client} · won {ago(r.won_at)}{r.final_value ? ` · ${money(r.final_value, r.currency || "USD")}` : ""}</div></div>
            {canEdit ? <button className="btn-primary h-9" disabled={start.isPending} onClick={() => start.mutate(r.deal_id)}>{start.isPending && start.variables === r.deal_id ? <Spinner /> : <Rocket className="h-4 w-4" />} Start project</button>
              : <span className="text-[12px] text-ink-muted">A delivery, presales or finance user can start it.</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function NewProject({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", client_name: "", currency: "INR", contract_value: "", budget_cost: "", start_date: new Date().toISOString().slice(0, 10), end_date: "" });
  const go = useMutation({
    mutationFn: () => api.post<any>("/projects", f),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["projects"] }); onClose(); nav(`/app/projects/${p.id}`); },
    onError: (e: any) => toast("error", e.message),
  });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open={open} onClose={onClose} title="New project">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go.mutate(); }}>
        <p className="text-[12.5px] text-ink-muted">For work that didn't come through a bid here, such as a renewal or a direct award. Won deals start their project from the deal.</p>
        <div><label className="label">Project name</label><input className="input" required value={f.name} onChange={set("name")} /></div>
        <div><label className="label">Client</label><input className="input" value={f.client_name} onChange={set("client_name")} /></div>
        <div className="grid grid-cols-3 gap-3">
          <div><label className="label">Currency</label><input className="input" maxLength={3} value={f.currency} onChange={set("currency")} /></div>
          <div><label className="label">Contract value</label><input className="input num" type="number" min={0} value={f.contract_value} onChange={set("contract_value")} /></div>
          <div><label className="label">Budget (cost)</label><input className="input num" type="number" min={0} value={f.budget_cost} onChange={set("budget_cost")} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label">Start</label><input className="input" type="date" value={f.start_date} onChange={set("start_date")} /></div>
          <div><label className="label">Planned end</label><input className="input" type="date" value={f.end_date} onChange={set("end_date")} /></div>
        </div>
        <button className="btn-primary" disabled={go.isPending}>{go.isPending && <Spinner />} Create project</button>
      </form>
    </Modal>
  );
}

// ======================================================================= one project
type Field = { k: string; label: string; type?: "text" | "date" | "number" | "select" | "textarea"; options?: string[]; data?: boolean; req?: boolean; ph?: string };
type KindCfg = { kind: string; title: string; one: string; fields: Field[]; empty: string };

const LV = ["low", "medium", "high"];
const CFG: Record<string, KindCfg> = {
  milestone: { kind: "milestone", title: "Milestones", one: "milestone", empty: "No milestones yet.", fields: [
    { k: "title", label: "Milestone", req: true }, { k: "due_date", label: "Due", type: "date" }, { k: "status", label: "Status", type: "select", options: ["planned", "in_progress", "done"] },
    { k: "owner", label: "Owner" }, { k: "amount", label: "Billing on completion", type: "number" }, { k: "detail", label: "Detail", type: "textarea", data: true }] },
  member: { kind: "member", title: "Team", one: "person or role", empty: "No team yet.", fields: [
    { k: "title", label: "Role", req: true }, { k: "person", label: "Person (employee code or name)", data: true, ph: "Leave empty while the role is open" },
    { k: "allocation_pct", label: "Allocation %", type: "number", data: true }, { k: "location", label: "Location", data: true }, { k: "owner", label: "Phase" },
    { k: "status", label: "Status", type: "select", options: ["planned", "active", "released"] }, { k: "start", label: "From", type: "date", data: true }, { k: "end", label: "To", type: "date", data: true }] },
  invoice: { kind: "invoice", title: "Invoices", one: "invoice", empty: "No invoices yet.", fields: [
    { k: "title", label: "What it bills", req: true, ph: "e.g. Design sign-off" }, { k: "number", label: "Invoice number", data: true }, { k: "amount", label: "Amount", type: "number", req: true },
    { k: "status", label: "Status", type: "select", options: ["draft", "raised", "paid"] }, { k: "due_date", label: "Payment due", type: "date" }, { k: "done_date", label: "Paid on", type: "date" }] },
  cost: { kind: "cost", title: "Costs", one: "cost", empty: "No costs recorded yet.", fields: [
    { k: "title", label: "Cost", req: true, ph: "e.g. Team cost, October" }, { k: "amount", label: "Amount", type: "number", req: true },
    { k: "category", label: "Category", type: "select", options: ["labour", "partner", "licence", "travel", "infrastructure", "other"], data: true }, { k: "due_date", label: "Date", type: "date" }] },
  change: { kind: "change", title: "Change requests", one: "change request", empty: "No change requests.", fields: [
    { k: "title", label: "Change", req: true }, { k: "amount", label: "Value (adds to the contract when approved)", type: "number" }, { k: "status", label: "Status", type: "select", options: ["proposed", "approved", "rejected"] },
    { k: "effort_days", label: "Effort (person-days)", type: "number", data: true }, { k: "schedule_days", label: "Schedule impact (days)", type: "number", data: true }, { k: "reason", label: "Reason", type: "textarea", data: true }] },
  risk: { kind: "risk", title: "Risks", one: "risk", empty: "No risks logged.", fields: [
    { k: "title", label: "Risk", req: true }, { k: "impact", label: "Impact", type: "select", options: LV, data: true }, { k: "likelihood", label: "Likelihood", type: "select", options: LV, data: true },
    { k: "status", label: "Status", type: "select", options: ["open", "mitigating", "closed"] }, { k: "owner", label: "Owner" }, { k: "mitigation", label: "Mitigation", type: "textarea", data: true }] },
  issue: { kind: "issue", title: "Issues", one: "issue", empty: "No issues logged.", fields: [
    { k: "title", label: "Issue", req: true }, { k: "severity", label: "Severity", type: "select", options: LV, data: true }, { k: "status", label: "Status", type: "select", options: ["open", "resolved"] },
    { k: "owner", label: "Owner" }, { k: "resolution", label: "Resolution", type: "textarea", data: true }] },
  sla: { kind: "sla", title: "Service levels by month", one: "SLA month", empty: "No SLA months recorded. Add one per month for managed services.", fields: [
    { k: "title", label: "Month", req: true, ph: "e.g. 2026-11" }, { k: "due_date", label: "Month end", type: "date" }, { k: "target_pct", label: "Target %", type: "number", data: true },
    { k: "achieved_pct", label: "Achieved %", type: "number", data: true }, { k: "incidents", label: "Incidents", type: "number", data: true }, { k: "breaches", label: "SLA breaches", type: "number", data: true }] },
  update: { kind: "update", title: "Status reports", one: "status report", empty: "No status reports yet.", fields: [
    { k: "title", label: "Headline", req: true }, { k: "status", label: "Reported health", type: "select", options: ["green", "amber", "red"] },
    { k: "done", label: "Done since last report", type: "textarea", data: true }, { k: "next", label: "Next", type: "textarea", data: true }, { k: "blockers", label: "Blockers / help needed", type: "textarea", data: true }] },
};

const TABS: [string, string][] = [["overview", "Overview"], ["plan", "Plan"], ["team", "Team"], ["money", "Money"], ["risks", "Risks & issues"], ["service", "Service"], ["updates", "Status reports"]];

export function ProjectPage() {
  const { id = "", tab = "overview" } = useParams();
  const { data: p, isLoading, error } = useQuery({ queryKey: ["project", id], queryFn: () => api.get<any>(`/projects/${id}`) });
  const [editing, setEditing] = useState(false);
  const canEdit = useCanEdit();
  if (isLoading) return <PageLoader />;
  if (error || !p) return <div className="p-8 text-ink-muted">{(error as Error)?.message || "Project not found."}</div>;
  const items = (k: string) => p.items.filter((i: any) => i.kind === k);
  const s = p.summary;
  return (
    <div className="px-4 lg:px-6 py-6 max-w-[1480px]">
      <Link to="/app/projects" className="text-[13px] text-ink-muted hover:text-ink inline-flex items-center gap-1"><ArrowLeft className="h-3.5 w-3.5" /> Projects</Link>
      <div className="mt-3 flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="flex-1 min-w-[min(100%,30rem)]">
          <div className="flex items-start gap-3 flex-wrap">
            <h1 className="font-display font-semibold text-[26px] md:text-[30px] leading-[1.1] tracking-[-0.02em] text-ink">{p.name}</h1>
            <span className="mt-2 flex gap-2"><ProjectStatus s={p.status} /><Health h={s.health} reasons={s.health_reasons} /></span>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 text-[13.5px] text-ink-muted">
            <Link to={`/app/clients/${p.client_key}`} className="font-semibold text-ink-soft hover:underline inline-flex items-center gap-1"><Building2 className="h-3.5 w-3.5" />{p.client || "Client not named"}</Link>
            {p.engagement_type && <><span className="text-ink-faint">·</span><span>{ENGAGEMENT[p.engagement_type] || p.engagement_type}</span></>}
            <span className="text-ink-faint">·</span><span>{day(p.start_date)} → {day(p.end_date)}</span>
            {p.manager && <><span className="text-ink-faint">·</span><span>Manager {p.manager.name}</span></>}
            {p.deal && <><span className="text-ink-faint">·</span><Link to={`/app/deals/${p.deal.id}`} className="text-brand-700 hover:underline inline-flex items-center gap-1"><Briefcase className="h-3.5 w-3.5" />The bid</Link></>}
          </div>
        </div>
        {canEdit && <div className="flex gap-2"><StatusMenu p={p} /><button className="btn-outline" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" /> Edit</button></div>}
      </div>

      <div className="mt-5 flex gap-1 overflow-x-auto border-b border-line-soft">
        {TABS.map(([k, l]) => {
          const n = k === "risks" ? s.risks_open + s.issues_open : k === "money" ? s.overdue_count : k === "plan" ? s.milestones.late : 0;
          return (
            <Link key={k} to={`/app/projects/${id}/${k}`} className={clsx("px-3.5 py-2.5 text-[13.5px] font-semibold whitespace-nowrap border-b-2 -mb-px transition-colors",
              tab === k ? "border-brand-500 text-ink" : "border-transparent text-ink-muted hover:text-ink")}>
              {l}{n > 0 && <span className={clsx("ml-1.5 chip h-[18px] px-1.5", k === "risks" ? "bg-line-soft text-ink-soft" : "bg-fit-gap-soft text-fit-gap-ink")}>{n}</span>}
            </Link>
          );
        })}
      </div>

      <div className="mt-5 space-y-5">
        {tab === "overview" && <Overview p={p} />}
        {tab === "plan" && <><Timeline p={p} /><Items p={p} cfg={CFG.milestone} rows={items("milestone")} canEdit={canEdit} /></>}
        {tab === "team" && <><TeamSummary rows={items("member")} /><Items p={p} cfg={CFG.member} rows={items("member")} canEdit={canEdit} /></>}
        {tab === "money" && <><MoneySummary p={p} /><Items p={p} cfg={CFG.invoice} rows={items("invoice")} canEdit={canEdit} money />
          <Items p={p} cfg={CFG.change} rows={items("change")} canEdit={canEdit} money /><Items p={p} cfg={CFG.cost} rows={items("cost")} canEdit={canEdit} money /></>}
        {tab === "risks" && <><Items p={p} cfg={CFG.risk} rows={items("risk")} canEdit={canEdit} /><Items p={p} cfg={CFG.issue} rows={items("issue")} canEdit={canEdit} /></>}
        {tab === "service" && <Items p={p} cfg={CFG.sla} rows={items("sla")} canEdit={canEdit} />}
        {tab === "updates" && <Updates p={p} rows={items("update")} canEdit={canEdit} />}
      </div>
      <EditProject p={p} open={editing} onClose={() => setEditing(false)} />
    </div>
  );
}

function useProjectMutation(pid: string) {
  const qc = useQueryClient();
  const toast = useToast();
  return (fn: (b: any) => Promise<any>, ok?: string) => useMutation({
    mutationFn: fn,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["project", pid] }); qc.invalidateQueries({ queryKey: ["projects"] }); qc.invalidateQueries({ queryKey: ["clients"] }); if (ok) toast("ok", ok); },
    onError: (e: any) => toast("error", e.message),
  });
}

function StatusMenu({ p }: { p: any }) {
  const m = useProjectMutation(p.id)((status: string) => api.patch(`/projects/${p.id}`, { status }), "Project status updated.");
  return (
    <select className="input h-9 w-auto" value={p.status} disabled={m.isPending} aria-label="Project status"
      onChange={(e) => (e.target.value !== "completed" || confirm("Close the project as completed? You can reopen it later.")) && m.mutate(e.target.value)}>
      {Object.entries(STATUS_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
    </select>
  );
}

function EditProject({ p, open, onClose }: { p: any; open: boolean; onClose: () => void }) {
  const { data: team } = useQuery({ queryKey: ["users"], queryFn: () => api.get<any[]>("/auth/users"), enabled: open });
  const [f, setF] = useState<any>(null);
  const m = useProjectMutation(p.id)((b: any) => api.patch(`/projects/${p.id}`, b), "Project saved.");
  const cur = f || { name: p.name, client_name: p.client, description: p.description, currency: p.currency, contract_value: p.contract_value, budget_cost: p.budget_cost,
    start_date: p.start_date, end_date: p.end_date, manager_id: p.manager?.id || "" };
  const set = (k: string) => (e: any) => setF({ ...cur, [k]: e.target.value });
  return (
    <Modal open={open} onClose={() => { setF(null); onClose(); }} title="Edit project" wide>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); const b = { ...cur }; if (!b.manager_id) delete b.manager_id; m.mutate(b, { onSuccess: () => { setF(null); onClose(); } }); }}>
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label">Name</label><input className="input" required value={cur.name} onChange={set("name")} /></div>
          <div><label className="label">Client</label><input className="input" value={cur.client_name} onChange={set("client_name")} /></div>
        </div>
        <div className="grid sm:grid-cols-3 gap-3">
          <div><label className="label">Currency</label><input className="input" maxLength={3} value={cur.currency} onChange={set("currency")} /></div>
          <div><label className="label">Contract value (as signed)</label><input className="input num" type="number" min={0} value={cur.contract_value} onChange={set("contract_value")} /></div>
          <div><label className="label">Budget (cost to deliver)</label><input className="input num" type="number" min={0} value={cur.budget_cost} onChange={set("budget_cost")} /></div>
        </div>
        <div className="grid sm:grid-cols-3 gap-3">
          <div><label className="label">Start</label><input className="input" type="date" value={cur.start_date} onChange={set("start_date")} /></div>
          <div><label className="label">Planned end</label><input className="input" type="date" value={cur.end_date} onChange={set("end_date")} /></div>
          <div><label className="label">Project manager</label><select className="input" value={cur.manager_id} onChange={set("manager_id")}>
            <option value="">—</option>{(team || []).filter((u: any) => u.active && u.role !== "viewer").map((u: any) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></div>
        </div>
        <div><label className="label">Scope and notes</label><textarea className="input h-24" value={cur.description} onChange={set("description")} /></div>
        <button className="btn-primary" disabled={m.isPending}>{m.isPending && <Spinner />} Save</button>
      </form>
    </Modal>
  );
}

function Card({ title, children, action, className }: { title: string; children: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <section className={clsx("card", className)}>
      <div className="px-5 py-3.5 border-b border-line-soft flex items-center gap-2"><div className="font-bold flex-1">{title}</div>{action}</div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Overview({ p }: { p: any }) {
  const s = p.summary;
  const c = p.currency || "USD";
  const bid = p.bid;
  const upcoming = p.items.filter((i: any) => i.kind === "milestone" && i.status !== "done").slice(0, 5);
  const risks = p.items.filter((i: any) => i.kind === "risk" && i.status !== "closed").sort((a: any, b: any) => LV.indexOf(b.data.impact) - LV.indexOf(a.data.impact)).slice(0, 5);
  const last = p.items.filter((i: any) => i.kind === "update").sort((a: any, b: any) => (a.created_at < b.created_at ? 1 : -1))[0];
  return (
    <>
      <div className={clsx("rounded-xl2 border px-5 py-4 flex flex-wrap gap-4 items-start",
        s.health === "red" ? "border-fit-gap/30 bg-fit-gap-soft" : s.health === "amber" ? "border-fit-partial/30 bg-fit-partial-soft" : "border-line bg-surface")}>
        <Health h={s.health} big />
        <div className="flex-1 min-w-[240px] text-[13.5px]">
          {s.health_reasons.length ? <ul className="space-y-1">{s.health_reasons.map((r: string) => <li key={r} className="flex gap-2"><AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 opacity-70" />{r}</li>)}</ul>
            : s.health === "closed" ? <span>Project closed{p.actual_end_date ? ` on ${day(p.actual_end_date)}` : ""}.</span>
            : <span className="text-ink-soft">Nothing late, overdue or over budget, and no open high-impact risks.</span>}
          {s.reported_health && s.reported_health !== s.health && s.health !== "closed" && (
            <div className="mt-2 text-[12.5px] text-ink-muted">The last status report said <b>{s.reported_health}</b>; the numbers say <b>{s.health}</b>.</div>)}
        </div>
      </div>
      <StatStrip items={[
        { label: "Milestones done", value: s.progress_pct == null ? "—" : `${s.progress_pct}%`, sub: `${s.milestones.done} of ${s.milestones.total}${s.milestones.late ? ` · ${s.milestones.late} late` : ""}${s.time_pct != null ? ` · ${s.time_pct}% of time used` : ""}`, tone: s.milestones.late ? "gap" : undefined },
        { label: "Contract value", value: money(s.value_total, c), sub: s.approved_changes ? `incl. ${money(s.approved_changes, c)} of changes` : s.pending_changes ? `${s.pending_changes} change(s) pending` : "as signed" },
        { label: "Invoiced / paid", value: money(s.invoiced, c), sub: `${money(s.paid, c)} paid · ${money(s.unbilled, c)} not billed yet` },
        { label: "Outstanding", value: money(s.outstanding, c), sub: s.overdue ? `${money(s.overdue, c)} overdue` : "nothing overdue", tone: s.overdue ? "gap" : undefined },
        { label: "Cost vs budget", value: s.burn_pct == null ? "—" : `${s.burn_pct}%`, sub: `${money(s.cost_actual, c)} of ${money(s.budget_cost, c)}`, tone: s.burn_pct != null && s.progress_pct != null && s.burn_pct - s.progress_pct > 10 ? "gap" : undefined },
        { label: "Margin", value: s.forecast_margin_pct != null ? `${s.forecast_margin_pct}%` : s.planned_margin_pct != null ? `${s.planned_margin_pct}%` : "—",
          sub: s.forecast_margin_pct != null ? `forecast at this pace · planned ${s.planned_margin_pct ?? "—"}%` : "planned · a forecast needs costs and 10% of milestones done" },
      ]} />
      <div className="grid lg:grid-cols-3 gap-5">
        <Card title="Coming up" className="lg:col-span-2" action={<Link to={`/app/projects/${p.id}/plan`} className="text-[12.5px] text-brand-700 font-semibold">Plan <ChevronRight className="inline h-3.5 w-3.5" /></Link>}>
          {!upcoming.length ? <div className="text-[13px] text-ink-muted">No open milestones.</div> : (
            <ul className="space-y-2.5">{upcoming.map((m: any) => (
              <li key={m.id} className="flex items-center gap-3 text-[13.5px]">
                <CalendarClock className={clsx("h-4 w-4 shrink-0", m.late ? "text-fit-gap-ink" : "text-ink-faint")} />
                <span className="flex-1 min-w-0 truncate">{m.title}</span>
                <span className={clsx("num text-[12.5px]", m.late ? "text-fit-gap-ink font-semibold" : "text-ink-muted")}>{m.late ? "late · " : ""}{day(m.due_date)}</span>
              </li>))}</ul>)}
        </Card>
        <Card title="From the bid">
          {!bid ? <div className="text-[13px] text-ink-muted">Started without a bid in RevenueForge.</div> : (
            <dl className="grid grid-cols-2 gap-y-2.5 text-[13px]">
              <dt className="text-ink-muted">Verdict</dt><dd className="font-semibold">{bid.verdict || "—"}</dd>
              <dt className="text-ink-muted">Readiness</dt><dd className="num">{bid.readiness ?? "—"}%{bid.mitigated_readiness != null ? ` → ${bid.mitigated_readiness}% with plan` : ""}</dd>
              <dt className="text-ink-muted">Bid price</dt><dd className="num">{money(bid.price, c)}{bid.scenario ? ` (${bid.scenario})` : ""}</dd>
              <dt className="text-ink-muted">Bid margin</dt><dd className="num">{bid.margin_pct ?? "—"}%</dd>
              <dt className="text-ink-muted">Planned team</dt><dd className="num">{bid.headcount ?? "—"} people · {bid.months ?? "—"} months</dd>
            </dl>)}
        </Card>
        <Card title="Open risks" className="lg:col-span-2" action={<Link to={`/app/projects/${p.id}/risks`} className="text-[12.5px] text-brand-700 font-semibold">All risks <ChevronRight className="inline h-3.5 w-3.5" /></Link>}>
          {!risks.length ? <div className="text-[13px] text-ink-muted">No open risks.</div> : (
            <ul className="space-y-2.5">{risks.map((r: any) => (
              <li key={r.id} className="text-[13.5px]"><div className="flex items-center gap-2"><Level v={r.data.impact} /><span className="font-semibold flex-1 min-w-0 truncate">{r.title}</span></div>
                {r.data.mitigation && <div className="text-[12.5px] text-ink-muted mt-0.5 pl-[52px]">{r.data.mitigation}</div>}</li>))}</ul>)}
        </Card>
        <Card title="Last status report" action={<Link to={`/app/projects/${p.id}/updates`} className="text-[12.5px] text-brand-700 font-semibold">Reports <ChevronRight className="inline h-3.5 w-3.5" /></Link>}>
          {!last ? <div className="text-[13px] text-ink-muted">No reports yet.</div> : (
            <div className="text-[13px] space-y-1.5"><div className="flex items-center gap-2"><Health h={last.status} /><span className="text-ink-muted text-[12px]">{ago(last.created_at)}</span></div>
              <div className="font-semibold">{last.title}</div>{last.data.blockers && <div className="text-ink-soft"><b>Blockers:</b> {last.data.blockers}</div>}</div>)}
        </Card>
      </div>
    </>
  );
}

function Level({ v }: { v?: string }) {
  if (!v) return <span className="chip bg-line-soft text-ink-muted">—</span>;
  return <span className={clsx("chip capitalize w-[60px] justify-center", v === "high" ? "bg-fit-gap-soft text-fit-gap-ink" : v === "medium" ? "bg-fit-partial-soft text-fit-partial-ink" : "bg-line-soft text-ink-muted")}>{v}</span>;
}

/** Milestones on a line from start to end, with today marked. */
function Timeline({ p }: { p: any }) {
  const ms = p.items.filter((i: any) => i.kind === "milestone" && i.due_date);
  const s = Date.parse(p.start_date), e = Date.parse(p.end_date);
  if (!ms.length || !(e > s)) return null;
  const end = Math.max(e, ...ms.map((m: any) => Date.parse(m.due_date)));
  const x = (d: number) => Math.max(0, Math.min(100, ((d - s) / (end - s)) * 100));
  const today = x(Date.now());
  return (
    <section className="card px-6 pt-5 pb-14">
      <div className="flex text-[12px] text-ink-muted mb-6"><span>{day(p.start_date)}</span><span className="flex-1" /><span>{day(p.end_date)}</span></div>
      <div className="relative h-1.5 rounded-full bg-line-soft">
        <div className="absolute inset-y-0 left-0 rounded-full bg-brand-500/30" style={{ width: `${today}%` }} />
        <div className="absolute -top-3 -bottom-3 w-px bg-ember-500" style={{ left: `${today}%` }} title="Today"><span className="absolute -top-4 -translate-x-1/2 text-[10.5px] font-bold text-ember-600">Today</span></div>
        {ms.map((m: any, i: number) => {
          const at = x(Date.parse(m.due_date));
          // labels alternate above and below the line, and lean inwards at the ends so they stay inside the card
          const pos = at > 88 ? "right-0 text-right" : at < 12 ? "left-0 text-left" : "left-1/2 -translate-x-1/2 text-center";
          return (
            <div key={m.id} className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: `${at}%` }} title={`${m.title} · ${day(m.due_date)} · ${m.status.replace("_", " ")}`}>
              <div className={clsx("h-3.5 w-3.5 rotate-45 rounded-[3px] ring-2 ring-surface", m.status === "done" ? "bg-ok" : m.late ? "bg-fit-gap" : m.status === "in_progress" ? "bg-brand-500" : "bg-ink-faint")} />
              <div className={clsx("absolute w-[118px] text-[10.5px] leading-tight text-ink-muted", pos, i % 2 ? "bottom-5" : "top-5")}>{m.title.replace(/ complete$/, "")}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function TeamSummary({ rows }: { rows: any[] }) {
  const live = rows.filter((r) => r.status !== "released");
  const open = live.filter((r) => !r.data.person);
  const fte = live.reduce((a, r) => a + (Number(r.data.allocation_pct ?? 100) || 0), 0) / 100;
  return <StatStrip items={[
    { label: "People and roles", value: live.length, sub: `${rows.length - live.length} released` },
    { label: "FTE", value: fte.toFixed(1), sub: "sum of allocations" },
    { label: "Open roles", value: open.length, sub: open.length ? "no one named yet" : "every role has a person", tone: open.length ? "gap" : undefined },
  ]} />;
}

function MoneySummary({ p }: { p: any }) {
  const s = p.summary;
  const c = p.currency || "USD";
  const parts = [{ l: "Paid", v: s.paid, cls: "bg-ok" }, { l: "Invoiced, not paid", v: s.outstanding - s.overdue, cls: "bg-brand-500" }, { l: "Overdue", v: s.overdue, cls: "bg-fit-gap" }, { l: "Not billed yet", v: Math.max(0, s.unbilled), cls: "bg-line" }];
  const total = parts.reduce((a, x) => a + Math.max(0, x.v), 0) || 1;
  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 mb-3">
        <div className="font-bold">Contract value {money(s.value_total, c)}</div>
        <div className="text-[12.5px] text-ink-muted">as signed {money(p.contract_value, c)}{s.approved_changes ? ` + ${money(s.approved_changes, c)} approved changes` : ""}{s.pending_changes ? ` · ${s.pending_changes} pending` : ""}</div>
      </div>
      <div className="flex h-3 rounded-full overflow-hidden bg-line-soft">{parts.map((x) => x.v > 0 && <div key={x.l} className={x.cls} style={{ width: `${(x.v / total) * 100}%` }} title={`${x.l}: ${money(x.v, c)}`} />)}</div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2.5 text-[12.5px]">{parts.map((x) => <span key={x.l} className="inline-flex items-center gap-1.5"><span className={clsx("h-2 w-2 rounded-full", x.cls)} />{x.l} <b className="num">{money(Math.max(0, x.v), c)}</b></span>)}</div>
      <div className="mt-4 pt-4 border-t border-line-soft grid sm:grid-cols-3 gap-3 text-[13px]">
        <div><div className="text-ink-muted text-[12px]">Cost to date</div><div className="num font-semibold">{money(s.cost_actual, c)} <span className="text-ink-muted font-normal">of {money(s.budget_cost, c)} budget{s.burn_pct != null ? ` (${s.burn_pct}%)` : ""}</span></div></div>
        <div><div className="text-ink-muted text-[12px]">Planned margin</div><div className="num font-semibold">{s.planned_margin_pct ?? "—"}%</div></div>
        <div><div className="text-ink-muted text-[12px]">Forecast margin</div><div className="num font-semibold">{s.forecast_margin_pct != null ? `${s.forecast_margin_pct}%` : "—"}
          <span className="text-ink-muted font-normal">{s.forecast_cost ? ` · cost at this pace ${money(s.forecast_cost, c)}` : " · needs costs and 10% of milestones done"}</span></div></div>
      </div>
    </section>
  );
}

const STATUS_STYLE: Record<string, string> = {
  done: "bg-ok-bg text-ok", paid: "bg-ok-bg text-ok", approved: "bg-ok-bg text-ok", closed: "bg-line-soft text-ink-muted", resolved: "bg-ok-bg text-ok", released: "bg-line-soft text-ink-muted",
  in_progress: "bg-brand-500/10 text-brand-700", active: "bg-brand-500/10 text-brand-700", raised: "bg-brand-500/10 text-brand-700", mitigating: "bg-brand-500/10 text-brand-700",
  open: "bg-fit-partial-soft text-fit-partial-ink", proposed: "bg-fit-partial-soft text-fit-partial-ink", rejected: "bg-line-soft text-ink-muted",
  green: "bg-ok-bg text-ok", amber: "bg-fit-partial-soft text-fit-partial-ink", red: "bg-fit-gap-soft text-fit-gap-ink",
};

function Items({ p, cfg, rows, canEdit, money: isMoney }: { p: any; cfg: KindCfg; rows: any[]; canEdit: boolean; money?: boolean }) {
  const [edit, setEdit] = useState<any>(null);  // {} for new, an item to change
  const mk = useProjectMutation(p.id);
  const quick = mk((b: any) => api.patch(`/projects/${p.id}/items/${b.id}`, { status: b.status }));
  const del = mk((id: string) => api.del(`/projects/${p.id}/items/${id}`), "Removed.");
  const c = p.currency || "USD";
  const shown = cfg.fields.filter((f) => f.type !== "textarea" && f.k !== "title" && f.k !== "status");
  const statusField = cfg.fields.find((f) => f.k === "status");
  const total = isMoney ? rows.reduce((a, r) => a + (cfg.kind === "change" && r.status !== "approved" ? 0 : r.amount || 0), 0) : 0;
  const val = (r: any, f: Field) => {
    const v = f.data ? r.data?.[f.k] : r[f.k];
    if (v == null || v === "" || (f.k === "amount" && !v && cfg.kind === "milestone")) return <span className="text-ink-faint">—</span>;
    if (f.type === "date") return <span className={clsx(r.late && f.k === "due_date" && "text-fit-gap-ink font-semibold")}>{r.late && f.k === "due_date" ? "late · " : ""}{day(v)}</span>;
    if (f.k === "amount") return <span className="num">{money(v, c)}</span>;
    if (f.k === "impact" || f.k === "likelihood" || f.k === "severity") return <Level v={v} />;
    if (f.k === "achieved_pct") return <span className={clsx("num", r.data?.target_pct != null && Number(v) < Number(r.data.target_pct) && "text-fit-gap-ink font-semibold")}>{v}%</span>;
    if (f.k === "target_pct" || f.k === "allocation_pct") return <span className="num">{v}%</span>;
    if (f.type === "number") return <span className="num">{v}</span>;
    return <span>{String(v)}</span>;
  };
  return (
    <section className="card">
      <div className="px-5 py-3.5 border-b border-line-soft flex items-center gap-2">
        <div className="font-bold flex-1">{cfg.title} <span className="text-ink-muted font-normal text-[13px]">· {rows.length}{isMoney && total ? ` · ${money(total, c)}${cfg.kind === "change" ? " approved" : ""}` : ""}</span></div>
        {canEdit && <button className="btn-outline h-8 text-[13px]" onClick={() => setEdit({})}><Plus className="h-3.5 w-3.5" /> Add {cfg.one}</button>}
      </div>
      {!rows.length ? <div className="px-5 py-6 text-[13px] text-ink-muted">{cfg.empty}</div> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px]">
            <thead><tr><th className="th">{cfg.fields[0].label}</th>{statusField && <th className="th">Status</th>}{shown.map((f) => <th key={f.k} className={clsx("th", f.type === "number" && "text-right")}>{f.label.replace(/ \(.*\)$/, "")}</th>)}{canEdit && <th className="th w-[80px]" />}</tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-ink/[.02] group">
                  <td className="td"><div className="font-semibold">{r.title}</div>
                    {cfg.fields.filter((f) => f.type === "textarea").map((f) => r.data?.[f.k] && <div key={f.k} className="text-[12.5px] text-ink-muted mt-0.5 max-w-[460px]">{f.label}: {r.data[f.k]}</div>)}</td>
                  {statusField && <td className="td">{canEdit ? (
                    <select className={clsx("chip border-0 cursor-pointer pr-2 appearance-none capitalize", STATUS_STYLE[r.status] || "bg-line-soft text-ink-muted")} value={r.status}
                      aria-label="Status" onChange={(e) => quick.mutate({ id: r.id, status: e.target.value })}>
                      {statusField.options!.map((o) => <option key={o} value={o}>{o.replace("_", " ")}</option>)}</select>)
                    : <span className={clsx("chip capitalize", STATUS_STYLE[r.status])}>{r.status.replace("_", " ")}</span>}</td>}
                  {shown.map((f) => <td key={f.k} className={clsx("td text-[13px]", f.type === "number" && "text-right")}>{val(r, f)}</td>)}
                  {canEdit && <td className="td text-right whitespace-nowrap">
                    <button className="btn-ghost h-7 w-7 p-0 opacity-60 group-hover:opacity-100" onClick={() => setEdit(r)} aria-label={`Edit ${r.title}`}><Pencil className="h-3.5 w-3.5" /></button>
                    <button className="btn-ghost h-7 w-7 p-0 opacity-60 group-hover:opacity-100" onClick={() => confirm(`Remove "${r.title}"?`) && del.mutate(r.id)} aria-label={`Remove ${r.title}`}><Trash2 className="h-3.5 w-3.5" /></button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {edit && <ItemForm p={p} cfg={cfg} item={edit.id ? edit : null} onClose={() => setEdit(null)} />}
    </section>
  );
}

function ItemForm({ p, cfg, item, onClose }: { p: any; cfg: KindCfg; item: any | null; onClose: () => void }) {
  const init = useMemo(() => {
    const v: Record<string, any> = {};
    cfg.fields.forEach((f) => { v[f.k] = item ? (f.data ? item.data?.[f.k] : item[f.k]) ?? "" : f.k === "status" ? f.options![0] : ""; });
    return v;
  }, [item, cfg]);
  const [v, setV] = useState<Record<string, any>>(init);
  const save = useProjectMutation(p.id)((body: any) => item ? api.patch(`/projects/${p.id}/items/${item.id}`, body) : api.post(`/projects/${p.id}/items`, body), item ? "Saved." : "Added.");
  const submit = () => {
    const body: any = { kind: cfg.kind, data: {} };
    cfg.fields.forEach((f) => {
      const x = v[f.k];
      if (f.data) body.data[f.k] = x === "" ? null : x;
      else if (!(x === "" && f.type === "number")) body[f.k] = x;
    });
    if (!item && body.amount === undefined) delete body.amount;
    save.mutate(body, { onSuccess: onClose });
  };
  return (
    <Modal open onClose={onClose} title={item ? `Edit ${cfg.one}` : `Add ${cfg.one}`} wide>
      <form className="grid sm:grid-cols-2 gap-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        {cfg.fields.map((f) => (
          <div key={f.k} className={clsx(f.type === "textarea" || f.k === "title" ? "sm:col-span-2" : "")}>
            <label className="label">{f.label}{f.k === "amount" ? ` (${p.currency || "USD"})` : ""}</label>
            {f.type === "select" ? (
              <select className="input capitalize" value={v[f.k] ?? ""} onChange={(e) => setV({ ...v, [f.k]: e.target.value })}>
                {f.data && <option value="">—</option>}{f.options!.map((o) => <option key={o} value={o}>{o.replace("_", " ")}</option>)}</select>
            ) : f.type === "textarea" ? (
              <textarea className="input h-20" value={v[f.k] ?? ""} onChange={(e) => setV({ ...v, [f.k]: e.target.value })} />
            ) : (
              <input className={clsx("input", f.type === "number" && "num")} type={f.type || "text"} required={f.req} placeholder={f.ph}
                step={f.type === "number" ? "any" : undefined} value={v[f.k] ?? ""} onChange={(e) => setV({ ...v, [f.k]: e.target.value })} />
            )}
          </div>
        ))}
        <div className="sm:col-span-2 flex gap-2 pt-1">
          <button className="btn-primary" disabled={save.isPending}>{save.isPending ? <Spinner /> : <Check className="h-4 w-4" />} {item ? "Save" : "Add"}</button>
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  );
}

function Updates({ p, rows, canEdit }: { p: any; rows: any[]; canEdit: boolean }) {
  const [adding, setAdding] = useState(false);
  const sorted = [...rows].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  return (
    <section className="card">
      <div className="px-5 py-3.5 border-b border-line-soft flex items-center gap-2">
        <div className="font-bold flex-1">Status reports <span className="text-ink-muted font-normal text-[13px]">· {rows.length}</span></div>
        {canEdit && <button className="btn-primary h-8 text-[13px]" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" /> New report</button>}
      </div>
      {!sorted.length ? <div className="px-5 py-6 text-[13px] text-ink-muted">No status reports yet. A short weekly report keeps everyone, and Client 360, up to date.</div> : (
        <ol className="divide-y divide-line-soft">
          {sorted.map((u) => (
            <li key={u.id} className="px-5 py-4">
              <div className="flex items-center gap-2"><Health h={u.status} /><span className="font-semibold flex-1">{u.title}</span><span className="text-[12px] text-ink-muted">{ago(u.created_at)}</span></div>
              <div className="grid md:grid-cols-3 gap-3 mt-2 text-[13px]">
                {[["done", "Done"], ["next", "Next"], ["blockers", "Blockers"]].map(([k, l]) => u.data?.[k] ? <div key={k}><div className="text-[11.5px] font-bold uppercase tracking-wide text-ink-muted">{l}</div><div className="text-ink-soft whitespace-pre-line">{u.data[k]}</div></div> : null)}
              </div>
            </li>
          ))}
        </ol>
      )}
      {adding && <ItemForm p={p} cfg={CFG.update} item={null} onClose={() => setAdding(false)} />}
    </section>
  );
}

// ======================================================================= client 360
export function Clients() {
  const { data, isLoading } = useQuery({ queryKey: ["clients"], queryFn: () => api.get<any[]>("/clients") });
  if (isLoading || !data) return <PageLoader />;
  return (
    <div className="px-4 lg:px-8 py-6 max-w-[1400px] space-y-5">
      <div>
        <h1 className={H1}>Client 360</h1>
        <p className="text-[13.5px] text-ink-muted mt-1">Every bid and project for each client in one place: what you've won and lost, what's being delivered, and what they owe.</p>
      </div>
      {!data.length ? (
        <div className="card"><Empty icon={<Building2 className="h-8 w-8" />} title="No clients yet">Clients appear here when you start a deal or a project for them.</Empty></div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[960px]">
            <thead><tr>
              <th className="th">Client</th><th className="th">Bids</th><th className="th text-right">Win rate</th><th className="th">Projects</th>
              <th className="th text-right">Contracted</th><th className="th text-right">Outstanding</th><th className="th">Delivery health</th><th className="th">Last activity</th>
            </tr></thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.key} className="hover:bg-ink/[.02]">
                  <td className="td"><Link to={`/app/clients/${c.key}`} className="font-semibold hover:text-brand-700">{c.name}</Link>{c.industry && <div className="text-[12.5px] text-ink-muted">{c.industry}</div>}</td>
                  <td className="td text-[13px]">{c.deals.total}<span className="text-ink-muted"> · {c.deals.won} won · {c.deals.lost} lost{c.deals.open ? ` · ${c.deals.open} open` : ""}</span></td>
                  <td className="td text-right num">{c.win_rate == null ? "—" : `${c.win_rate}%`}</td>
                  <td className="td text-[13px]">{c.projects.total ? `${c.projects.live} live of ${c.projects.total}` : <span className="text-ink-faint">—</span>}</td>
                  <td className="td text-right num">{sumMoney(c.contracted)}</td>
                  <td className="td text-right num">{sumMoney(c.outstanding)}{Object.keys(c.overdue || {}).length > 0 && <div className="text-[11.5px] text-fit-gap-ink font-semibold">{sumMoney(c.overdue)} overdue</div>}</td>
                  <td className="td"><Health h={c.health} /></td>
                  <td className="td text-[12.5px] text-ink-muted">{ago(c.last_activity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const EVENT_DOT: Record<string, string> = { won: "bg-ok", paid: "bg-ok", milestone: "bg-brand-500", lost: "bg-fit-gap", no_bid: "bg-ink-faint", change: "bg-ember-500", project: "bg-brand-500", update: "bg-fit-partial" };

export function ClientPage() {
  const { key = "" } = useParams();
  const { data: c, isLoading, error } = useQuery({ queryKey: ["clients", key], queryFn: () => api.get<any>(`/clients/${key}`) });
  if (isLoading) return <PageLoader />;
  if (error || !c) return <div className="p-8 text-ink-muted">{(error as Error)?.message || "Client not found."}</div>;
  return (
    <div className="px-4 lg:px-6 py-6 max-w-[1480px] space-y-5">
      <div>
        <Link to="/app/clients" className="text-[13px] text-ink-muted hover:text-ink inline-flex items-center gap-1"><ArrowLeft className="h-3.5 w-3.5" /> Client 360</Link>
        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <h1 className="font-display font-semibold text-[26px] md:text-[30px] leading-[1.1] tracking-[-0.02em] text-ink">{c.name}</h1>
          <Health h={c.health} />
        </div>
        {c.industry && <div className="text-[13.5px] text-ink-muted mt-1">{c.industry}</div>}
      </div>
      <StatStrip items={[
        { label: "Bids", value: c.deals.total, sub: `${c.deals.won} won · ${c.deals.lost} lost · ${c.deals.open} open` },
        { label: "Win rate", value: c.win_rate == null ? "—" : `${c.win_rate}%`, sub: "of decided bids" },
        { label: "Contracted", value: sumMoney(c.contracted), sub: `${c.projects.live} live project(s) of ${c.projects.total}` },
        { label: "Paid", value: sumMoney(c.paid), sub: `invoiced ${sumMoney(c.invoiced)}` },
        { label: "Outstanding", value: sumMoney(c.outstanding), sub: Object.keys(c.overdue || {}).length ? `${sumMoney(c.overdue)} overdue` : "nothing overdue", tone: Object.keys(c.overdue || {}).length ? "gap" : undefined },
      ]} />
      <div className="grid lg:grid-cols-3 gap-5 items-start">
        <div className="lg:col-span-2 space-y-5">
          <Card title={`Projects · ${c.project_list.length}`}>
            {!c.project_list.length ? <div className="text-[13px] text-ink-muted">No projects yet.</div> : (
              <ul className="divide-y divide-line-soft -my-2">{c.project_list.map((p: any) => (
                <li key={p.id} className="py-3 flex flex-wrap items-center gap-3 text-[13.5px]">
                  <div className="flex-1 min-w-[220px]"><Link to={`/app/projects/${p.id}`} className="font-semibold hover:text-brand-700">{p.name}</Link>
                    <div className="text-[12.5px] text-ink-muted">{day(p.start_date)} → {day(p.end_date)} · {STATUS_LABEL[p.status]}</div></div>
                  <div className="w-[130px]">{p.summary.progress_pct != null && <><Meter value={p.summary.progress_pct} /><div className="text-[11.5px] text-ink-muted mt-1">{p.summary.progress_pct}% of milestones</div></>}</div>
                  <div className="text-right num w-[120px]">{money(p.summary.value_total, p.currency)}<div className="text-[11.5px] text-ink-muted">{money(p.summary.outstanding, p.currency)} due</div></div>
                  <Health h={p.summary.health} reasons={p.summary.health_reasons} />
                </li>))}</ul>)}
          </Card>
          <Card title={`Bids · ${c.deal_list.length}`}>
            {!c.deal_list.length ? <div className="text-[13px] text-ink-muted">No bids in RevenueForge.</div> : (
              <ul className="divide-y divide-line-soft -my-2">{c.deal_list.map((d: any) => (
                <li key={d.id} className="py-3 flex flex-wrap items-center gap-3 text-[13.5px]">
                  <div className="flex-1 min-w-[220px]"><Link to={`/app/deals/${d.id}`} className="font-semibold hover:text-brand-700">{d.name}</Link>
                    <div className="text-[12.5px] text-ink-muted">{ago(d.created_at)}{d.engagement_type ? ` · ${ENGAGEMENT[d.engagement_type]}` : ""}{d.verdict ? ` · verdict ${d.verdict}` : ""}{d.readiness != null ? ` (${d.readiness}% ready)` : ""}</div></div>
                  <div className="text-right num w-[130px]">{money(d.final_value || d.value, d.currency || "USD")}<div className="text-[11.5px] text-ink-muted">{d.final_value ? "agreed" : "bid price"}</div></div>
                  <DealStatus s={d.status} />
                </li>))}</ul>)}
          </Card>
        </div>
        <Card title="Timeline">
          {!c.timeline.length ? <div className="text-[13px] text-ink-muted">Nothing yet.</div> : (
            <ol className="relative border-l border-line ml-1.5 space-y-4">{c.timeline.map((e: any, i: number) => (
              <li key={i} className="pl-4 relative">
                <span className={clsx("absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface", EVENT_DOT[e.kind] || "bg-ink-faint")} />
                <Link to={e.link} className="text-[13px] hover:text-brand-700 block">{e.text}{e.amount ? <span className="num text-ink-muted"> · {money(e.amount, e.currency)}</span> : null}</Link>
                <div className="text-[11.5px] text-ink-muted">{ago(e.at)}</div>
              </li>))}</ol>)}
        </Card>
      </div>
    </div>
  );
}
