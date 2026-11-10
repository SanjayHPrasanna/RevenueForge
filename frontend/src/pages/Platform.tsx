import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Activity, AlertTriangle, Bot, Building2, CheckCircle2, LogOut, PauseCircle, PlayCircle, RefreshCw, Search, ShieldAlert, ShieldCheck, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Empty, Modal, Spinner, StatStrip, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

type Tab = "overview" | "companies" | "ai" | "health" | "security";
const TABS: { key: Tab; label: string; icon: any }[] = [
  { key: "overview", label: "Overview", icon: Activity },
  { key: "companies", label: "Companies & people", icon: Building2 },
  { key: "ai", label: "AI usage", icon: Bot },
  { key: "health", label: "System health", icon: ShieldCheck },
  { key: "security", label: "Security", icon: ShieldAlert },
];
const ROLES = ["admin", "presales", "architect", "finance", "delivery", "viewer"];
const C = { a: "#118AC3", b: "#F5833A", c: "#0C3D55", d: "#B4232A", grid: "#E6EDF1", ink: "#5B6B76" };

const num = (n: number | undefined) => (n ?? 0).toLocaleString();
const day = (iso?: string) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "—");
const when = (iso?: string) => {
  if (!iso) return "Never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "Just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)} days ago`;
  return new Date(iso).toLocaleDateString();
};
const bytes = (b: number) => (b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`);
const short = (d: string) => d.slice(5).replace("-", "/");

function Card({ title, sub, children, right }: { title: string; sub?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="card p-5">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div><div className="font-bold">{title}</div>{sub && <div className="text-[12.5px] text-ink-muted mt-0.5">{sub}</div>}</div>
        {right}
      </div>
      {children}
    </section>
  );
}

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return <span className={clsx("inline-block h-2.5 w-2.5 rounded-full", ok ? "bg-emerald-500" : warn ? "bg-amber-500" : "bg-rose-600")} />;
}

function Days({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex gap-1">
      {[7, 30, 90].map((d) => (
        <button key={d} onClick={() => onChange(d)} className={clsx("chip border px-2 py-1", value === d ? "bg-brand-700 text-white border-brand-700" : "bg-white border-line text-ink-soft")}>{d} days</button>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------- overview
function Overview() {
  const [days, setDays] = useState(30);
  const { data: o, isLoading } = useQuery({ queryKey: ["pf-overview", days], queryFn: () => api.get<any>(`/platform/overview?days=${days}`), refetchInterval: 60000 });
  if (isLoading || !o) return <div className="py-16 grid place-items-center"><Spinner /></div>;
  return (
    <div className="space-y-5">
      <StatStrip items={[
        { label: "Companies", value: num(o.companies.total), sub: `${o.companies.sellers} sellers · ${o.companies.buyers} buyers${o.companies.paused ? ` · ${o.companies.paused} paused` : ""}` },
        { label: "People", value: num(o.people.total), sub: `${o.people.active_7d} active this week · ${o.people.active_30d} this month` },
        { label: "Deals", value: num(o.deals.total), sub: `${o.deals.new} new in ${days} days`, tone: "brand" },
        { label: "AI calls", value: num(o.ai.calls), sub: `${o.ai.failure_pct}% failed · ${num(o.ai.tokens)} tokens`, tone: o.ai.failure_pct > 10 ? "gap" : undefined },
        { label: "Failed sign-ins", value: num(o.security.failed_sign_ins), sub: `${num(o.security.sign_ins)} successful sign-ins`, tone: o.security.failed_sign_ins > 20 ? "gap" : undefined },
      ]} />
      <Card title="Activity" sub={`Every company, last ${days} days. Counts only: no company content.`} right={<Days value={days} onChange={setDays} />}>
        <div className="h-[260px]">
          <ResponsiveContainer>
            <LineChart data={o.series} margin={{ left: -18, right: 8, top: 6 }}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="day" tickFormatter={short} tick={{ fontSize: 11, fill: C.ink }} minTickGap={24} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: C.ink }} />
              <Tooltip labelFormatter={(d) => day(String(d))} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="sign_ins" name="Sign-ins" stroke={C.a} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="deals" name="Deals started" stroke={C.b} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="new_companies" name="New companies" stroke={C.c} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Deals by status" sub="Across all companies">
          <Rows rows={Object.entries(o.deals.by_status).map(([k, v]) => ({ label: k.replace("_", " "), value: v as number }))} />
        </Card>
        <Card title="People by role" sub="Across all companies">
          <Rows rows={ROLES.map((r) => ({ label: r, value: o.people.roles[r] || 0 }))} />
        </Card>
      </div>
    </div>
  );
}

function Rows({ rows, plain }: { rows: { label: string; value: number }[]; plain?: boolean }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <div className="text-[13px] text-ink-muted">Nothing yet.</div>;
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className={clsx("grid items-center gap-3 text-[13px]", plain ? "grid-cols-[minmax(0,220px)_1fr_48px]" : "grid-cols-[110px_1fr_48px]")}>
          <span className={clsx("text-ink-soft truncate", !plain && "capitalize")} title={r.label}>{r.label}</span>
          <div className="h-2.5 rounded-full bg-line-soft overflow-hidden"><div className="h-full bg-brand-500 rounded-full" style={{ width: `${(100 * r.value) / max}%` }} /></div>
          <span className="num text-right font-semibold">{num(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------- companies
function Companies() {
  const { data, isLoading } = useQuery({ queryKey: ["pf-companies"], queryFn: () => api.get<any[]>("/platform/companies"), refetchInterval: 60000 });
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(() => (data || []).filter((c) => !q || c.name.toLowerCase().includes(q.toLowerCase())), [data, q]);
  if (isLoading) return <div className="py-16 grid place-items-center"><Spinner /></div>;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 max-w-sm">
        <div className="relative w-full"><Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input className="input w-full pl-9" placeholder="Find a company" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      </div>
      <section className="card overflow-x-auto">
        <table className="w-full min-w-[980px] text-[13px]">
          <thead><tr><th className="th">Company</th><th className="th">Status</th><th className="th text-right">People</th><th className="th">Last active</th>
            <th className="th text-right">Deals (30 d)</th><th className="th">Library</th><th className="th">AI</th><th className="th text-right">Storage</th></tr></thead>
          <tbody>{rows.map((c) => (
            <tr key={c.id} className="border-t border-line-soft hover:bg-paper cursor-pointer" onClick={() => setOpen(c.id)}>
              <td className="td"><div className="font-semibold text-brand-900">{c.name}{c.is_mine && <span className="chip bg-brand-50 text-brand-700 ml-2">Yours</span>}</div>
                <div className="text-[11.5px] text-ink-muted">{c.kind === "buyer" ? "Buyer" : "Seller"} · since {day(c.created_at)}</div></td>
              <td className="td">{c.paused ? <span className="chip bg-rose-50 text-rose-700">Paused</span> : <span className="chip bg-emerald-50 text-emerald-700">Active</span>}</td>
              <td className="td text-right num">{c.people}{c.people_paused ? <div className="text-[11px] text-ink-muted">{c.people_paused} paused</div> : null}</td>
              <td className="td">{when(c.last_active)}<div className="text-[11px] text-ink-muted">{c.active_30d} active this month</div></td>
              <td className="td text-right num">{c.deals}<span className="text-ink-muted"> ({c.deals_30d})</span></td>
              <td className="td text-[12px] text-ink-soft">{c.library.capabilities} capabilities · {c.library.people} people · {c.library.case_studies} case studies</td>
              <td className="td text-[12px]">{c.ai.own_key ? <b>Own key</b> : "Server"} · {c.ai.provider}<div className="text-ink-muted">{num(c.ai.calls_30d)} calls{c.ai.failures_30d ? `, ${c.ai.failures_30d} failed` : ""}</div></td>
              <td className="td text-right num">{bytes(c.storage_bytes)}</td>
            </tr>))}</tbody>
        </table>
        {!rows.length && <Empty icon={<Building2 className="h-8 w-8" />} title="No companies found" />}
      </section>
      {open && <CompanyDetail id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function CompanyDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: c } = useQuery({ queryKey: ["pf-company", id], queryFn: () => api.get<any>(`/platform/companies/${id}`) });
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: any }) => api.post(path, body || {}),
    onSuccess: (_r, v) => { qc.invalidateQueries({ queryKey: ["pf-company", id] }); qc.invalidateQueries({ queryKey: ["pf-companies"] }); toast("ok", v.path.includes("signout") ? "Signed out everywhere." : "Done."); },
    onError: (e: any) => toast("error", e.message),
  });
  return (
    <Modal open onClose={onClose} title={c?.name || "Company"} xl>
      {!c ? <div className="py-12 grid place-items-center"><Spinner /></div> : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-3 text-[13px]">
            {c.paused ? <span className="chip bg-rose-50 text-rose-700">Paused{c.pause_reason ? `: ${c.pause_reason}` : ""}</span> : <span className="chip bg-emerald-50 text-emerald-700">Active</span>}
            <span className="text-ink-muted">{c.kind === "buyer" ? "Buyer" : "Seller"} · since {day(c.created_at)} · {c.deals} deals · {bytes(c.storage_bytes)} of files · AI: {c.ai?.own_key ? `own ${c.ai.provider} key` : "server default"}</span>
          </div>
          {!c.is_mine && (
            <div className="card p-4 flex flex-wrap items-center gap-3 bg-paper">
              {c.paused ? (
                <button className="btn-outline" disabled={act.isPending} onClick={() => act.mutate({ path: `/platform/companies/${id}/reactivate` })}><PlayCircle className="h-4 w-4" /> Reactivate company</button>
              ) : (
                <>
                  <input className="input flex-1 min-w-[220px]" placeholder="Reason shown to them (optional), e.g. unpaid invoice" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
                  <button className="btn-outline text-rose-700 border-rose-200" disabled={act.isPending}
                    onClick={() => window.confirm(`Pause ${c.name}? Nobody in it can sign in or use RevenueForge until you reactivate it. Their data stays as it is.`) && act.mutate({ path: `/platform/companies/${id}/pause`, body: { reason } })}>
                    <PauseCircle className="h-4 w-4" /> Pause company</button>
                </>
              )}
            </div>
          )}
          <div>
            <div className="font-bold mb-2 flex items-center gap-2"><Users className="h-4 w-4" /> People</div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-[13px]">
                <thead><tr><th className="th">Person</th><th className="th">Role</th><th className="th">Sign-in</th><th className="th">Last active</th><th className="th">Status</th><th className="th text-right">Actions</th></tr></thead>
                <tbody>{c.people_list.map((p: any) => (
                  <tr key={p.id} className="border-t border-line-soft">
                    <td className="td"><div className="font-medium">{p.name}{p.platform_admin && <span className="chip bg-brand-50 text-brand-700 ml-2">Platform admin</span>}</div><div className="text-[12px] text-ink-muted">{p.email}</div></td>
                    <td className="td">
                      <select className="input py-1 text-[13px]" value={p.role} disabled={p.is_me || act.isPending}
                        onChange={(e) => act.mutate({ path: `/platform/users/${p.id}/role`, body: { role: e.target.value } })}>
                        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </td>
                    <td className="td text-ink-soft">{p.sso}</td>
                    <td className="td">{when(p.last_active)}</td>
                    <td className="td">{p.active ? <span className="chip bg-emerald-50 text-emerald-700">Active</span> : <span className="chip bg-rose-50 text-rose-700">Paused</span>}</td>
                    <td className="td text-right whitespace-nowrap">
                      {!p.is_me && (p.active ? (
                        <button className="btn-ghost text-[12.5px] py-1" disabled={act.isPending} onClick={() => window.confirm(`Pause ${p.name}? They are signed out at once and can't sign in until reactivated.`) && act.mutate({ path: `/platform/users/${p.id}/pause` })}><PauseCircle className="h-3.5 w-3.5" /> Pause</button>
                      ) : (
                        <button className="btn-ghost text-[12.5px] py-1" disabled={act.isPending} onClick={() => act.mutate({ path: `/platform/users/${p.id}/reactivate` })}><PlayCircle className="h-3.5 w-3.5" /> Reactivate</button>
                      ))}
                      {!p.is_me && p.active && <button className="btn-ghost text-[12.5px] py-1" disabled={act.isPending} title="Ends every session on every device; they can sign in again"
                        onClick={() => act.mutate({ path: `/platform/users/${p.id}/signout` })}><LogOut className="h-3.5 w-3.5" /> Sign out everywhere</button>}
                    </td>
                  </tr>))}</tbody>
              </table>
            </div>
          </div>
          <div className="grid lg:grid-cols-2 gap-5">
            <Card title="Activity" sub="Sign-ins, deals started and AI calls per day">
              <div className="h-[200px]"><ResponsiveContainer>
                <LineChart data={c.series} margin={{ left: -18, right: 8, top: 6 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="day" tickFormatter={short} tick={{ fontSize: 11, fill: C.ink }} minTickGap={24} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: C.ink }} /><Tooltip labelFormatter={(d) => day(String(d))} /><Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line dataKey="sign_ins" name="Sign-ins" stroke={C.a} strokeWidth={2} dot={false} /><Line dataKey="deals" name="Deals" stroke={C.b} strokeWidth={2} dot={false} />
                  <Line dataKey="ai_calls" name="AI calls" stroke={C.c} strokeWidth={2} dot={false} />
                </LineChart></ResponsiveContainer></div>
            </Card>
            <Card title="AI by model" sub="Last 30 days">
              {c.ai_models.length ? <table className="w-full text-[12.5px]"><thead><tr><th className="th">Model</th><th className="th text-right">Calls</th><th className="th text-right">Failed</th><th className="th text-right">Tokens</th><th className="th text-right">Avg</th></tr></thead>
                <tbody>{c.ai_models.map((m: any) => <tr key={m.provider + m.model} className="border-t border-line-soft"><td className="td">{m.provider} · {m.model}</td><td className="td text-right num">{num(m.calls)}</td>
                  <td className={clsx("td text-right num", m.failures && "text-rose-700")}>{num(m.failures)}</td><td className="td text-right num">{num(m.tokens)}</td><td className="td text-right num">{m.avg_seconds}s</td></tr>)}</tbody></table>
                : <div className="text-[13px] text-ink-muted">No AI calls in this period.</div>}
            </Card>
          </div>
          <Card title="Library size" sub="Counts only. The console never shows what is in a company's library or deals.">
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 text-center">
              {Object.entries(c.library || {}).map(([k, v]) => <div key={k} className="rounded-lg bg-paper py-2"><div className="num font-bold text-[18px]">{v as number}</div><div className="text-[11.5px] text-ink-muted capitalize">{k.replace("_", " ")}</div></div>)}
            </div>
          </Card>
          <Card title="Security events" sub="Latest 100 for this company">
            <Events rows={c.events} hideCompany />
          </Card>
        </div>
      )}
    </Modal>
  );
}

// --------------------------------------------------------------------------- AI
function Ai() {
  const [days, setDays] = useState(30);
  const { data: a, isLoading } = useQuery({ queryKey: ["pf-ai", days], queryFn: () => api.get<any>(`/platform/ai?days=${days}`), refetchInterval: 60000 });
  if (isLoading || !a) return <div className="py-16 grid place-items-center"><Spinner /></div>;
  const total = a.series.reduce((s: any, d: any) => ({ calls: s.calls + d.calls, failures: s.failures + d.failures, tokens: s.tokens + d.tokens }), { calls: 0, failures: 0, tokens: 0 });
  return (
    <div className="space-y-5">
      <StatStrip items={[
        { label: "AI calls", value: num(total.calls), sub: `last ${days} days` },
        { label: "Failed", value: num(total.failures), sub: total.calls ? `${((100 * total.failures) / total.calls).toFixed(1)}% of calls` : "—", tone: total.failures ? "gap" : undefined },
        { label: "Tokens", value: num(total.tokens), sub: "as reported by the providers" },
        { label: "Server default AI", value: a.server.provider || "off", sub: `${a.server.model || "auto"} · ${a.server.paid ? "paid" : "free"} key · ${a.server.rpm}/min`, tone: "brand" },
      ]} />
      {(a.server.disabled_reason || a.server.last_error) && (
        <div className="card px-5 py-3 border-rose-200 bg-rose-50/50 text-[13px] text-rose-800 flex gap-2"><AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span><b>Server AI:</b> {a.server.disabled_reason || a.server.last_error}</span></div>
      )}
      <Card title="Calls per day" sub="Successful and failed AI calls, all companies and the website chat" right={<Days value={days} onChange={setDays} />}>
        <div className="h-[240px]"><ResponsiveContainer>
          <BarChart data={a.series.map((d: any) => ({ ...d, ok: d.calls - d.failures }))} margin={{ left: -18, right: 8, top: 6 }}>
            <CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="day" tickFormatter={short} tick={{ fontSize: 11, fill: C.ink }} minTickGap={24} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: C.ink }} /><Tooltip labelFormatter={(d) => day(String(d))} /><Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="ok" name="Worked" stackId="a" fill={C.a} /><Bar dataKey="failures" name="Failed" stackId="a" fill={C.d} />
          </BarChart></ResponsiveContainer></div>
      </Card>
      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="By provider and model">
          <table className="w-full text-[12.5px]"><thead><tr><th className="th">Model</th><th className="th text-right">Calls</th><th className="th text-right">Failed</th><th className="th text-right">Tokens</th><th className="th text-right">Avg time</th></tr></thead>
            <tbody>{a.models.map((m: any) => <tr key={m.provider + m.model} className="border-t border-line-soft"><td className="td">{m.provider} · {m.model || "—"}</td><td className="td text-right num">{num(m.calls)}</td>
              <td className={clsx("td text-right num", m.failure_pct > 10 && "text-rose-700 font-semibold")}>{num(m.failures)} ({m.failure_pct}%)</td><td className="td text-right num">{num(m.tokens)}</td><td className="td text-right num">{m.avg_seconds}s</td></tr>)}</tbody></table>
          {!a.models.length && <div className="text-[13px] text-ink-muted mt-2">No AI calls in this period.</div>}
        </Card>
        <Card title="By company" sub="Which AI each company uses and how it's going">
          <table className="w-full text-[12.5px]"><thead><tr><th className="th">Company</th><th className="th">AI</th><th className="th text-right">Calls</th><th className="th text-right">Failed</th></tr></thead>
            <tbody>{a.companies.map((c: any) => <tr key={c.id} className="border-t border-line-soft"><td className="td font-medium">{c.name}</td><td className="td">{c.own_key ? <b>Own</b> : "Server"} · {c.provider}{c.model ? ` · ${c.model}` : ""}</td>
              <td className="td text-right num">{num(c.calls)}</td><td className={clsx("td text-right num", c.failure_pct > 10 && "text-rose-700 font-semibold")}>{num(c.failures)}</td></tr>)}
              <tr className="border-t border-line-soft"><td className="td text-ink-muted">Website chat (Maahi)</td><td className="td">{a.maahi_own_key ? "Maahi's own key" : "Server"}</td>
                <td className="td text-right num">{num(a.website_chat.calls)}</td><td className="td text-right num">{num(a.website_chat.failures)}</td></tr></tbody></table>
        </Card>
      </div>
      <div className="text-[12px] text-ink-muted">{a.note}</div>
    </div>
  );
}

// --------------------------------------------------------------------------- health
function Health() {
  const { data: h, isLoading, refetch, isFetching } = useQuery({ queryKey: ["pf-health"], queryFn: () => api.get<any>("/platform/health"), refetchInterval: 30000 });
  if (isLoading || !h) return <div className="py-16 grid place-items-center"><Spinner /></div>;
  const feedsOk = h.feeds.every((f: any) => !f.error && !f.stale);
  const checks = [
    { label: "Database", ok: h.database.ok, text: h.database.ok ? `${h.database.engine}, healthy` : `Damaged: ${h.database.detail}` },
    { label: "AI engine", ok: !h.ai.disabled_reason, warn: !!h.ai.last_error, text: h.ai.disabled_reason || (h.ai.last_error ? `Working, last error: ${h.ai.last_error.slice(0, 120)}` : `${h.ai.provider} · ${h.ai.model || "auto"}`) },
    { label: "Deals", ok: !h.deals.stuck_over_30_min, warn: h.deals.failed_7d > 0, text: `${h.deals.processing} running now · ${h.deals.stuck_over_30_min} stuck over 30 min · ${h.deals.failed_7d} failed this week` },
    { label: "Tender feeds", ok: feedsOk, warn: !feedsOk, text: `${num(h.tenders_open)} open tenders · ${num(h.awards_stored)} past awards` },
    { label: "Background jobs", ok: Object.values(h.background).every(Boolean), warn: true, text: Object.entries(h.background).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v ? "running" : "not running"}`).join(" · ") },
    { label: "Email", ok: h.services.email, warn: true, text: h.services.email ? "Configured" : "Not configured: no approval or deadline emails are sent" },
  ];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 text-[13px] text-ink-muted">
        <span>Checked {when(h.checked_at)}</span><span>· Up {h.uptime_hours} h (since {new Date(h.started_at).toLocaleString()})</span>{h.version && <span>· Version {h.version}</span>}
        <button className="btn-ghost py-1 text-[12.5px]" onClick={() => refetch()} disabled={isFetching}><RefreshCw className={clsx("h-3.5 w-3.5", isFetching && "animate-spin")} /> Refresh</button>
      </div>
      <section className="card divide-y divide-line-soft">
        {checks.map((c) => (
          <div key={c.label} className="px-5 py-3 grid grid-cols-[18px_160px_1fr] items-center gap-3 text-[13px]">
            <Dot ok={c.ok} warn={c.warn} /><span className="font-semibold">{c.label}</span><span className="text-ink-soft">{c.text}</span>
          </div>
        ))}
      </section>
      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Tender and award feeds" sub="Refreshed every 12 hours; stale means no success in 36 hours">
          <table className="w-full text-[12.5px]"><thead><tr><th className="th">Feed</th><th className="th">Last success</th><th className="th text-right">Read</th><th className="th">Status</th></tr></thead>
            <tbody>{h.feeds.map((f: any) => <tr key={f.key} className="border-t border-line-soft"><td className="td">{f.key}</td><td className="td">{when(f.last_ok)}</td><td className="td text-right num">{num(f.fetched)}</td>
              <td className="td">{f.error ? <span className="text-rose-700" title={f.error}>{f.error.slice(0, 60)}</span> : f.stale ? <span className="text-amber-700">Stale</span> : <span className="text-emerald-700">OK</span>}</td></tr>)}</tbody></table>
          {!h.feeds.length && <div className="text-[13px] text-ink-muted mt-2">No feed has run yet on this server.</div>}
        </Card>
        <Card title="Storage and sign-in">
          <div className="grid grid-cols-2 gap-3 text-[13px]">
            <div className="rounded-lg bg-paper p-3"><div className="text-ink-muted text-[12px]">Company files</div><div className="font-bold num">{bytes(h.disk.uploads)}</div></div>
            <div className="rounded-lg bg-paper p-3"><div className="text-ink-muted text-[12px]">Database file</div><div className="font-bold num">{h.disk.database ? bytes(h.disk.database) : "PostgreSQL"}</div></div>
            {h.disk.total ? <div className="rounded-lg bg-paper p-3 col-span-2"><div className="text-ink-muted text-[12px]">Disk free</div><div className="font-bold num">{bytes(h.disk.free)} of {bytes(h.disk.total)}</div></div> : null}
            <div className="col-span-2 text-ink-soft space-y-1">
              <div><Dot ok={h.services.google_sign_in} warn /> Google sign-in {h.services.google_sign_in ? "on" : "off"}</div>
              <div><Dot ok={h.services.microsoft_sign_in} warn /> Microsoft sign-in {h.services.microsoft_sign_in ? "on" : "off"}</div>
              <div><Dot ok={h.services.maahi_own_key} warn /> Maahi {h.services.maahi_own_key ? "has her own key" : "uses the server AI"}</div>
              <div><Dot ok /> {h.services.platform_admins} platform admin{h.services.platform_admins === 1 ? "" : "s"}</div>
            </div>
          </div>
        </Card>
      </div>
      <Card title="Recent warnings and errors" sub={h.note}>
        {h.recent_errors.length ? (
          <div className="max-h-[360px] overflow-auto text-[12.5px] font-mono divide-y divide-line-soft">
            {h.recent_errors.map((e: any, i: number) => (
              <div key={i} className="py-1.5 grid grid-cols-[120px_64px_1fr] gap-3">
                <span className="text-ink-muted">{when(e.at)}</span><span className={e.level === "ERROR" ? "text-rose-700 font-semibold" : "text-amber-700"}>{e.level}</span><span className="break-words">{e.message}</span>
              </div>))}
          </div>
        ) : <div className="text-[13px] text-ink-muted flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-600" /> No warnings since the last restart.</div>}
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- security
function Events({ rows, hideCompany }: { rows: any[]; hideCompany?: boolean }) {
  if (!rows?.length) return <div className="text-[13px] text-ink-muted">No events in this period.</div>;
  return (
    <div className="overflow-x-auto max-h-[420px]">
      <table className="w-full min-w-[720px] text-[12.5px]">
        <thead className="sticky top-0 bg-white"><tr><th className="th">When</th><th className="th">Event</th>{!hideCompany && <th className="th">Company</th>}<th className="th">Who</th><th className="th">Details</th></tr></thead>
        <tbody>{rows.map((e, i) => {
          const bad = /failed|Locked|deleted|paused|disabled/i.test(e.label);
          return (
            <tr key={i} className="border-t border-line-soft">
              <td className="td whitespace-nowrap text-ink-muted">{new Date(e.at).toLocaleString()}</td>
              <td className={clsx("td font-medium", bad && "text-rose-700")}>{e.label}</td>
              {!hideCompany && <td className="td">{e.company || <span className="text-ink-muted">No company</span>}</td>}
              <td className="td">{e.user}</td>
              <td className="td text-ink-soft">{[e.network && `from ${e.network}`, ...Object.entries(e.detail || {}).map(([k, v]) => `${k}: ${v}`)].filter(Boolean).join(" · ")}</td>
            </tr>);
        })}</tbody>
      </table>
    </div>
  );
}

function Security() {
  const [days, setDays] = useState(30);
  const { data: s, isLoading } = useQuery({ queryKey: ["pf-security", days], queryFn: () => api.get<any>(`/platform/security?days=${days}`), refetchInterval: 60000 });
  const [view, setView] = useState<"events" | "signins">("events");
  if (isLoading || !s) return <div className="py-16 grid place-items-center"><Spinner /></div>;
  return (
    <div className="space-y-5">
      <StatStrip items={[
        { label: "Sign-ins", value: num(s.summary.sign_ins), sub: `last ${days} days` },
        { label: "Failed sign-ins", value: num(s.summary.failed_sign_ins), sub: `${s.summary.lockouts} lockouts`, tone: s.summary.failed_sign_ins > 20 ? "gap" : undefined },
        { label: "Role changes", value: num(s.summary.role_changes) },
        { label: "Data exports", value: num(s.summary.exports), sub: `${s.summary.deletions} companies deleted` },
        { label: "Platform actions", value: num(s.summary.platform_actions), sub: "by platform admins", tone: "brand" },
      ]} />
      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Networks with failed sign-ins" sub="Many failures from one address can mean someone guessing passwords">
          <Rows plain rows={s.top_failing_networks.map((n: any) => ({ label: n.network, value: n.failures }))} />
        </Card>
        <Card title="Accounts with failed sign-ins" sub="Unknown emails are partly hidden">
          <Rows plain rows={s.top_failing_accounts.map((n: any) => ({ label: n.account, value: n.failures }))} />
        </Card>
      </div>
      <Card title={view === "events" ? "Security events" : "Successful sign-ins"} right={
        <div className="flex items-center gap-3"><div className="flex gap-1">
          {(["events", "signins"] as const).map((v) => <button key={v} onClick={() => setView(v)} className={clsx("chip border px-2 py-1", view === v ? "bg-brand-700 text-white border-brand-700" : "bg-white border-line text-ink-soft")}>{v === "events" ? "Events" : "Sign-ins"}</button>)}
        </div><Days value={days} onChange={setDays} /></div>}>
        <Events rows={view === "events" ? s.events : s.sign_ins} />
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- page
export default function Platform() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>(() => {
    try { return (sessionStorage.getItem("rf-platform-tab") as Tab) || "overview"; } catch { return "overview"; }
  });
  const pick = (t: Tab) => { setTab(t); try { sessionStorage.setItem("rf-platform-tab", t); } catch { /* ignore */ } };
  if (!user?.platform_admin) {
    return <div className="px-4 lg:px-8 py-10"><Empty icon={<ShieldAlert className="h-8 w-8" />} title="Platform admins only">This console is for the people who run this RevenueForge server.</Empty></div>;
  }
  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1400px] space-y-5">
      <div>
        <div className="eyebrow mb-1.5">Platform console</div>
        <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Every company, at a glance</h1>
        <p className="text-ink-muted text-[14px] mt-1">Usage, AI, system health and security across this server. You see companies, their people and counts, never their deals, library or files.</p>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-line" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => pick(t.key)}
            className={clsx("px-3 py-2 text-[13.5px] font-semibold border-b-2 -mb-px inline-flex items-center gap-1.5", tab === t.key ? "border-brand-700 text-brand-900" : "border-transparent text-ink-muted hover:text-ink")}>
            <t.icon className="h-4 w-4" /> {t.label}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview />}
      {tab === "companies" && <Companies />}
      {tab === "ai" && <Ai />}
      {tab === "health" && <Health />}
      {tab === "security" && <Security />}
    </div>
  );
}
