import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Download, ShieldCheck, Trash2, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { Modal, PageLoader, Spinner, useToast } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";

const ROLE_HELP: Record<string, string> = {
  admin: "Everything, including settings and users", presales: "Creates deals; approves requirements, matching and proposals",
  architect: "Approves architecture and estimation", finance: "Approves pricing; edits rates and margins",
  delivery: "Approves estimation and the handoff", viewer: "Read-only",
};

export default function SettingsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const { data: c } = useQuery({ queryKey: ["company"], queryFn: () => api.get("/company") });
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: () => api.get("/auth/users") });
  const [s, setS] = useState<any>(null);
  const [inv, setInv] = useState(false);
  const [nu, setNu] = useState({ name: "", email: "", role: "presales", password: "" });
  useEffect(() => { if (c && !s) setS({ ...c.settings, about: c.about }); }, [c]);
  const save = useMutation({
    mutationFn: () => api.put("/company", { about: s.about, settings: { target_margin: s.target_margin, min_margin: s.min_margin, travel_pct: s.travel_pct, hide_employee_names: s.hide_employee_names } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["company"] }); toast("ok", "Settings saved. New pricing runs use them."); },
    onError: (e: any) => toast("error", e.message),
  });
  const invite = useMutation({
    mutationFn: () => api.post("/auth/users", nu),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); setInv(false); toast("ok", `${nu.name} can now sign in.`); setNu({ name: "", email: "", role: "presales", password: "" }); },
    onError: (e: any) => toast("error", e.message),
  });
  const role = useMutation({
    mutationFn: ({ id, body }: any) => api.patch(`/auth/users/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e: any) => toast("error", e.message),
  });
  if (!c || !s) return <PageLoader />;
  const isAdmin = user?.role === "admin";
  return (
    <div className="px-4 lg:px-8 py-6 max-w-[1100px] space-y-4">
      <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Settings</h1>
      <MyEmails />
      {user?.tenant.kind !== "buyer" && <NetworkListing isAdmin={isAdmin} />}
      {user?.tenant.kind !== "buyer" && <section className="card p-5">
        <div className="font-bold">Commercial policy</div>
        <div className="text-[13px] text-ink-muted mb-4">Used by every pricing run. Finance can still adjust per deal.</div>
        <div className="flex flex-wrap gap-4">
          {[["target_margin", "Target margin"], ["min_margin", "Margin floor"], ["travel_pct", "Travel & living (% of onsite cost)"]].map(([k, l]) => (
            <label key={k} className="text-[13px]"><span className="label">{l}</span>
              <div className="relative"><input className="input w-32 num pr-7" type="number" value={s[k]} onChange={(e) => setS({ ...s, [k]: Number(e.target.value) })} disabled={!isAdmin} /><span className="absolute right-2.5 top-2.5 text-ink-faint text-[12px]">%</span></div>
            </label>
          ))}
        </div>
        <label className="flex items-center gap-2 mt-4 text-[13.5px]">
          <input type="checkbox" className="h-4 w-4 accent-[#118AC3]" checked={!!s.hide_employee_names} onChange={(e) => setS({ ...s, hide_employee_names: e.target.checked })} disabled={!isAdmin} />
          Show employee codes instead of names everywhere
        </label>
        <div className="mt-4"><label className="label" htmlFor="company-about">About the company (used in proposals)</label><textarea id="company-about" className="input h-24 py-2" value={s.about} onChange={(e) => setS({ ...s, about: e.target.value })} disabled={!isAdmin} /></div>
        {isAdmin && <button className="btn-primary mt-4" onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending && <Spinner />} Save settings</button>}
      </section>}

      <section className="card">
        <div className="px-5 py-3.5 border-b border-line flex items-center">
          <div><div className="font-bold">People in this workspace</div><div className="text-[13px] text-ink-muted">Each stage is approved by the role responsible for it.</div></div>
          <div className="flex-1" />
          {isAdmin && <button className="btn-outline" onClick={() => setInv(true)}><UserPlus className="h-4 w-4" /> Add person</button>}
        </div>
        <table className="w-full">
          <tbody>
            {(users || []).map((u: any) => (
              <tr key={u.id}>
                <td className="td"><div className="font-semibold">{u.name}</div><div className="text-[12.5px] text-ink-muted">{u.email}</div></td>
                <td className="td w-[200px]">
                  <select className="input h-9" aria-label={`Role for ${u.name}`} value={u.role} disabled={!isAdmin || u.id === user?.id} onChange={(e) => role.mutate({ id: u.id, body: { role: e.target.value } })}>
                    {Object.keys(ROLE_HELP).map((r) => <option key={r} value={r} className="capitalize">{r}</option>)}
                  </select>
                </td>
                <td className="td text-[12.5px] text-ink-muted hidden md:table-cell">{ROLE_HELP[u.role]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <AiEngine c={c} />

      {isAdmin && <CompanyData name={c.name} />}

      <Modal open={inv} onClose={() => setInv(false)} title="Add a person">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}>
          <div><label className="label">Name</label><input className="input" required value={nu.name} onChange={(e) => setNu({ ...nu, name: e.target.value })} /></div>
          <div><label className="label">Work email</label><input className="input" type="email" required value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} /></div>
          <div><label className="label">Role</label><select className="input" value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>{Object.keys(ROLE_HELP).map((r) => <option key={r}>{r}</option>)}</select><div className="text-[12px] text-ink-muted mt-1">{ROLE_HELP[nu.role]}</div></div>
          <div><label className="label">Temporary password</label><input className="input" type="text" minLength={8} value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} placeholder="Leave empty if they sign in with Google" /></div>
          <button className="btn-primary" disabled={invite.isPending}>Add person</button>
        </form>
      </Modal>
    </div>
  );
}

const PROVIDER_LABEL: Record<string, string> = { gemini: "Google Gemini", anthropic: "Anthropic Claude", openai: "OpenAI", azure: "Azure OpenAI", none: "Rules engine only (AI off)" };
const MODEL_HINT: Record<string, string> = { gemini: "Leave empty to use the newest Flash model", anthropic: "e.g. claude-sonnet-4-5", openai: "e.g. gpt-4o", azure: "Your deployment name" };

/** AI engine status for everyone; the change form only for the server's platform admins (the set-up is shared by every company). */
/** Each person chooses which emails they get. */
function MyEmails() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["my-prefs"], queryFn: () => api.get("/auth/me/prefs") });
  const save = useMutation({
    mutationFn: (emails: Record<string, boolean>) => api.put("/auth/me/prefs", { emails }),
    onSuccess: (d) => { qc.setQueryData(["my-prefs"], d); toast("ok", "Email preferences saved."); },
    onError: (e: any) => toast("error", e.message),
  });
  if (!data) return null;
  return (
    <section className="card p-5">
      <div className="font-bold">My email notifications</div>
      <div className="text-[13px] text-ink-muted mb-4">
        {data.email_enabled ? <>Sent to <span className="font-semibold text-ink">{data.email}</span>. Only you see these choices.</>
          : "Email isn't set up on this server yet (SMTP settings), so no emails are sent. Your choices are kept for when it is."}
      </div>
      <div className="grid sm:grid-cols-2 gap-2.5">
        {data.emails.map((e: any) => (
          <label key={e.key} className="flex items-center gap-3 rounded-xl border border-line-soft px-3.5 py-3 text-[13.5px] cursor-pointer hover:border-brand-200 hover:bg-brand-50/30 transition-colors">
            <input type="checkbox" className="h-4 w-4 accent-[#118AC3]" checked={e.on} disabled={save.isPending}
              onChange={(ev) => save.mutate({ [e.key]: ev.target.checked })} />
            {e.label}
          </label>
        ))}
      </div>
    </section>
  );
}

/** "List us in the supplier network": what buyers can find, and the preview of exactly what they'll see. */
function NetworkListing({ isAdmin }: { isAdmin: boolean }) {
  const toast = useToast();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["network-profile"], queryFn: () => api.get<any>("/network/profile") });
  const [f, setF] = useState<any>(null);
  const [preview, setPreview] = useState(false);
  useEffect(() => { if (data && !f) setF({ ...data.settings, industries: (data.settings.industries || []).join(", ") }); }, [data]);
  const save = useMutation({
    mutationFn: (body: any) => api.put<any>("/network/profile", body),
    onSuccess: (r) => { qc.setQueryData(["network-profile"], r); setF({ ...r.settings, industries: (r.settings.industries || []).join(", ") });
      toast("ok", r.settings.listed ? "Your company is listed in the supplier network." : "Your company is not listed in the supplier network."); },
    onError: (e: any) => toast("error", e.message),
  });
  if (!data || !f) return null;
  const body = () => ({ ...f, industries: String(f.industries || "").split(",").map((x: string) => x.trim()).filter(Boolean) });
  const p = data.preview;
  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-[280px]">
          <div className="font-bold">Supplier network</div>
          <div className="text-[13px] text-ink-muted mt-0.5">Let buyers who upload an RFP find you when your proven work matches it, and invite you to bid. Buyers see your capabilities, company certificates, case-study summaries without client names, and how many people have each skill. Never people's names, rates, deals or clients.</div>
        </div>
        <span className={`chip ${data.settings.listed ? "bg-[#E4F1F7] text-fit-strong-ink" : "bg-line-soft text-ink-muted"}`}>{data.settings.listed ? "Listed" : "Not listed"}</span>
      </div>
      <div className="grid md:grid-cols-2 gap-4 mt-4 text-[13px]">
        <div>
          <span className="label">Regions you serve</span>
          <div className="flex flex-wrap gap-1.5">
            {data.regions.map((r: string) => {
              const on = (f.regions || []).includes(r);
              return <button key={r} type="button" disabled={!isAdmin} onClick={() => setF({ ...f, regions: on ? f.regions.filter((x: string) => x !== r) : [...(f.regions || []), r] })}
                className={`chip border ${on ? "bg-brand-50 border-brand-300 text-brand-800" : "bg-white border-line text-ink-soft"}`} aria-pressed={on}>{r}</button>;
            })}
          </div>
        </div>
        <div className="space-y-3">
          <label className="block"><span className="label">Industries you focus on</span>
            <input className="input" disabled={!isAdmin} value={f.industries} onChange={(e) => setF({ ...f, industries: e.target.value })} placeholder="e.g. Healthcare, Transportation, Banking" /></label>
          <label className="block"><span className="label">Short description for buyers</span>
            <textarea className="input h-20 py-2" disabled={!isAdmin} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} placeholder="Leave empty to use 'About the company'" /></label>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {isAdmin && <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate({ ...body(), listed: !data.settings.listed })}>
          {save.isPending && <Spinner />} {data.settings.listed ? "Remove us from the network" : "List us in the supplier network"}</button>}
        {isAdmin && data.settings.listed && <button className="btn-outline" disabled={save.isPending} onClick={() => save.mutate(body())}>Save changes</button>}
        <button className="btn-ghost" onClick={() => setPreview(!preview)}>{preview ? "Hide" : "Preview"} what buyers see</button>
        {!isAdmin && <span className="text-[12.5px] text-ink-muted">Only company admins can change the listing.</span>}
      </div>
      {preview && (
        <div className="mt-4 rounded-lg border border-line-soft bg-paper p-4 text-[13px] space-y-2 anim-fade-in">
          <div><b>{p.name}</b> · {p.headquarters || "Headquarters not set"} · {p.headcount} people</div>
          <div><span className="text-ink-muted">Capabilities:</span> {p.capabilities.map((c: any) => c.name).join(", ") || "none yet"}</div>
          <div><span className="text-ink-muted">Certificates and partnerships:</span> {p.certifications.map((c: any) => c.name).join(", ") || "none"}</div>
          <div><span className="text-ink-muted">Case studies:</span> {p.case_studies.map((c: any) => c.title).join("; ") || "none yet"}</div>
          <div><span className="text-ink-muted">Skills (people):</span> {p.skills.map((s: any) => `${s.technology} ${s.people}`).join(", ") || "none"}</div>
        </div>
      )}
    </section>
  );
}

function AiEngine({ c }: { c: any }) {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["ai-config"], queryFn: () => api.get<any>("/auth/ai-config") });
  const [f, setF] = useState<any>(null);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  useEffect(() => {
    if (cfg?.can_edit && !f) setF({ provider: cfg.provider, api_key: "", model: cfg.provider === "gemini" ? (cfg.model || "") : cfg.model, rpm: cfg.rpm, paid: cfg.paid, azure_endpoint: cfg.azure_endpoint || "" });
  }, [cfg]);
  const refresh = (r: any) => { qc.setQueryData(["ai-config"], r); qc.invalidateQueries({ queryKey: ["company"] }); setF(null); setTest(null); };
  const save = useMutation({
    mutationFn: () => api.put("/auth/ai-config", f),
    onSuccess: (r) => { refresh(r); toast("ok", "AI engine updated for every company on this server."); },
    onError: (e: any) => toast("error", e.message),
  });
  const reset = useMutation({
    mutationFn: () => api.del("/auth/ai-config"),
    onSuccess: (r) => { refresh(r); toast("ok", "Back to the server's own AI settings."); },
    onError: (e: any) => toast("error", e.message),
  });
  const check = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>("/auth/ai-config/test"),
    onSuccess: (r) => { setTest(r); qc.invalidateQueries({ queryKey: ["company"] }); },
    onError: (e: any) => setTest({ ok: false, message: e.message }),
  });
  const hint = f && cfg?.key_hint?.[f.provider];
  return (
    <>
    <section className="card p-5 flex gap-4">
          <Cpu className="h-5 w-5 text-brand-600 mt-0.5 shrink-0" />
          <div className="text-[13.5px] flex-1 min-w-0">
            <div className="font-bold">AI engine</div>
            {c.llm.enabled ? (
              <>
                <div className="text-ink-soft mt-1">Using <b className="capitalize">{c.llm.provider}</b> ({c.llm.model}) {c.llm.source === "company" ? "with your company's own key" : "from the server's default AI"} to read RFPs, judge capability fit, plan mitigations, design the architecture and write answers. Semantic matching: {c.llm.embeddings ? "on (embeddings)" : "off (text matching)"}. If a call fails, that step falls back to the rules engine and the deal still completes.</div>
                <div className="mt-3 grid sm:grid-cols-4 gap-3 text-[12.5px]">
                  <div className="rounded bg-paper px-3 py-2"><div className="text-ink-muted">Tier</div><div className="font-semibold">{c.llm.paid ? "Paid" : "Free"}</div></div>
                  <div className="rounded bg-paper px-3 py-2"><div className="text-ink-muted">Rate limit used</div><div className="font-semibold num">{c.llm.rpm}/min</div></div>
                  {c.llm.calls != null && <>
                    <div className="rounded bg-paper px-3 py-2"><div className="text-ink-muted">AI calls since start</div><div className="font-semibold num">{c.llm.calls}</div></div>
                    <div className="rounded bg-paper px-3 py-2"><div className="text-ink-muted">Failed calls</div><div className={`font-semibold num ${c.llm.failures ? "text-fit-gap-ink" : ""}`}>{c.llm.failures}</div></div>
                  </>}
                </div>
                {!c.llm.paid && <div className="mt-3 rounded border border-ember-100 bg-ember-50 px-3 py-2 text-[12.5px] text-ember-600">Free tier: Google may use submitted content to improve its products and reviewers may read it. Don't process confidential client RFPs until the key is on a billed project; then tick "Paid / billed key" below (or set <code>LLM_PAID=true</code> on the server).</div>}
                {c.llm.last_error && <div className="mt-2 text-[12px] text-fit-gap-ink break-words">Last error: {c.llm.last_error}</div>}
              </>
            ) : (
              <div className="text-ink-soft mt-1">
                {c.llm.disabled_reason ? <span className="text-fit-gap-ink font-semibold">{c.llm.disabled_reason} </span> : "AI is off, so deals run on the built-in rules engine. "}
                To turn on Gemini, create <code className="bg-paper px-1 rounded">backend/.env</code> with:
                <pre className="mt-2 bg-paper rounded p-3 text-[12px] overflow-x-auto">LLM_PROVIDER=gemini{"\n"}GEMINI_API_KEY=your-key</pre>
                and restart. Claude, OpenAI and Azure OpenAI also work (see <code>backend/.env.example</code>).
              </div>
            )}
          </div>
        </section>
      <CompanyAi />
      {cfg?.can_edit && f && (
        <section className="card p-5">
          <div className="flex flex-wrap items-start gap-3">
            <div className="flex-1 min-w-[240px]">
              <div className="font-bold">Server default AI</div>
              <div className="text-[13px] text-ink-muted mt-0.5">Used by every company that hasn't added its own key. Only platform admins see this.
                {cfg.saved_in_app ? " Currently using settings saved here." : " Currently using the server's own settings."}</div>
            </div>
            {cfg.saved_in_app && <button className="btn-ghost" disabled={reset.isPending} onClick={() => confirm("Go back to the server's own AI settings? Keys saved here are removed.") && reset.mutate()}>Use server settings</button>}
          </div>
          <div className="grid md:grid-cols-2 gap-4 mt-4">
            <label className="text-[13px]"><span className="label">Provider</span>
              <select className="input" value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value, api_key: "", model: "" })}>
                {Object.entries(PROVIDER_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            {f.provider !== "none" && (
              <label className="text-[13px]"><span className="label">API key</span>
                <input className="input" type="password" autoComplete="off" value={f.api_key} onChange={(e) => setF({ ...f, api_key: e.target.value })}
                  placeholder={hint ? `Key ${hint} in use. Leave empty to keep it` : "Paste the API key"} />
              </label>
            )}
            {f.provider !== "none" && (
              <label className="text-[13px]"><span className="label">{f.provider === "azure" ? "Deployment" : "Model"}</span>
                <input className="input" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} placeholder={MODEL_HINT[f.provider]} />
              </label>
            )}
            {f.provider === "azure" && (
              <label className="text-[13px]"><span className="label">Azure OpenAI endpoint</span>
                <input className="input" value={f.azure_endpoint} onChange={(e) => setF({ ...f, azure_endpoint: e.target.value })} placeholder="https://your-resource.openai.azure.com" />
              <span className="block text-[11.5px] text-ink-muted mt-1">From the resource's Keys and Endpoint page. A Foundry ".services.ai.azure.com" address works too.</span>
              </label>
            )}
            {f.provider !== "none" && (
              <label className="text-[13px]"><span className="label">Requests per minute</span>
                <input className="input num w-32" type="number" min={1} max={1000} value={f.rpm} onChange={(e) => setF({ ...f, rpm: Number(e.target.value) || 1 })} />
              </label>
            )}
            {f.provider !== "none" && (
              <label className="flex items-start gap-2 text-[13px] pt-6">
                <input type="checkbox" className="h-4 w-4 mt-0.5 accent-[#118AC3]" checked={!!f.paid} onChange={(e) => setF({ ...f, paid: e.target.checked })} />
                <span>Paid / billed key<span className="block text-ink-muted text-[12px]">Tick only when the provider doesn't use your content for training. This hides the "sample data only" banner.</span></span>
              </label>
            )}
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending && <Spinner />} Save</button>
            <button className="btn-outline" disabled={check.isPending || save.isPending} onClick={() => check.mutate()}>{check.isPending && <Spinner />} Test connection</button>
            {test && <span className={`text-[13px] ${test.ok ? "text-ok" : "text-fit-gap-ink"}`}>{test.message}</span>}
          </div>
          <div className="mt-3 text-[12px] text-ink-muted">Keys are stored on the server only and never shown again; "Test connection" checks the settings currently in use (save first).</div>
        </section>
      )}
      {cfg && !cfg.can_edit && (
        <div className="text-[12.5px] text-ink-muted -mt-2 px-1">
          {cfg.admins_configured ? "The AI engine is shared by every company on this server and is managed by its platform admins." :
            "To manage the AI engine from here, add your email to PLATFORM_ADMINS in the server settings (backend/.env locally, or the App Service settings on Azure)."}
        </div>
      )}
    </>
  );
}

/** The company's own AI provider and key: company admins set it, and it applies to this company only. */
function CompanyAi() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const toast = useToast();
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["company-ai"], queryFn: () => api.get<any>("/company/ai") });
  const [f, setF] = useState<any>(null);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  useEffect(() => {
    if (cfg && !f) setF({ provider: cfg.provider, api_key: "", model: cfg.model || "", rpm: cfg.rpm || 8, paid: !!cfg.paid, azure_endpoint: cfg.azure_endpoint || "" });
  }, [cfg]);
  const done = (r: any, msg: string) => { qc.setQueryData(["company-ai"], r); qc.invalidateQueries({ queryKey: ["company"] }); setF(null); setTest(null); toast("ok", msg); };
  const save = useMutation({
    mutationFn: () => api.put("/company/ai", f),
    onSuccess: (r) => done(r, f.provider === "default" ? "Your company now uses the server's default AI." : "Your company's AI key is saved and in use."),
    onError: (e: any) => toast("error", e.message),
  });
  const check = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>("/company/ai/test", f),  // checks the form as filled in; saves nothing
    onSuccess: (r) => setTest(r),
    onError: (e: any) => setTest({ ok: false, message: e.message }),
  });
  if (!cfg || !f) return null;
  const own = f.provider !== "default";
  const hint = own ? cfg.key_hint?.[f.provider] : "";
  const sd = cfg.server_default;
  return (
    <section className="card p-5">
      <div className="font-bold">Your company's AI</div>
      <div className="text-[13px] text-ink-muted mt-0.5">Bring your own provider and key. It applies to your company only: your deals, imports, videos and learning. {isAdmin ? "Only company admins can change it." : "Ask a company admin to change it."}</div>
      <div className="mt-4 grid sm:grid-cols-2 gap-3 max-w-3xl">
        {[["default", "Use the server's default AI", sd?.provider && sd.provider !== "none" ? `Currently ${PROVIDER_LABEL[sd.provider]}${sd.provider === "gemini" && !sd.paid ? " (free key)" : ""}` : "Currently off: rules engine only"],
          ["own", "Use our own key", "Gemini, Claude, OpenAI or Azure OpenAI"]].map(([k, l, d]) => {
          const on = k === "own" ? own : !own;
          return (
            <button key={k} type="button" disabled={!isAdmin} onClick={() => setF({ ...f, provider: k === "own" ? (own ? f.provider : "gemini") : "default", api_key: "" })}
              className={`text-left rounded-lg border px-4 py-3 transition-colors ${on ? "border-brand-500 bg-brand-50" : "border-line hover:border-brand-200"}`}>
              <div className="flex items-center gap-2 font-semibold text-[14px]"><span className={`h-3.5 w-3.5 rounded-full border-2 ${on ? "border-brand-600 bg-brand-600 shadow-[inset_0_0_0_2px_white]" : "border-ink-faint"}`} />{l}</div>
              <div className="text-[12.5px] text-ink-muted mt-1 pl-[22px]">{d}</div>
            </button>
          );
        })}
      </div>
      {own && isAdmin && (
        <div className="grid md:grid-cols-2 gap-4 mt-4">
          <label className="text-[13px]"><span className="label">Provider</span>
            <select className="input" value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value, api_key: "", model: "" })}>
              {["gemini", "anthropic", "openai", "azure"].map((k) => <option key={k} value={k}>{PROVIDER_LABEL[k]}</option>)}
            </select>
          </label>
          <label className="text-[13px]"><span className="label">API key</span>
            <input className="input" type="password" autoComplete="off" value={f.api_key} onChange={(e) => setF({ ...f, api_key: e.target.value })}
              placeholder={hint ? `Key ${hint} saved. Leave empty to keep it` : "Paste your API key"} />
          </label>
          <label className="text-[13px]"><span className="label">{f.provider === "azure" ? "Deployment" : "Model"}</span>
            <input className="input" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} placeholder={MODEL_HINT[f.provider]} />
          </label>
          {f.provider === "azure" && (
            <label className="text-[13px]"><span className="label">Azure OpenAI endpoint</span>
              <input className="input" value={f.azure_endpoint} onChange={(e) => setF({ ...f, azure_endpoint: e.target.value })} placeholder="https://your-resource.openai.azure.com" />
              <span className="block text-[11.5px] text-ink-muted mt-1">From the resource's Keys and Endpoint page. A Foundry ".services.ai.azure.com" address works too.</span>
            </label>
          )}
          <label className="text-[13px]"><span className="label">Requests per minute</span>
            <input className="input num w-32" type="number" min={1} max={1000} value={f.rpm} onChange={(e) => setF({ ...f, rpm: Number(e.target.value) || 1 })} />
          </label>
          {f.provider === "gemini" && (
            <label className="flex items-start gap-2 text-[13px] pt-6">
              <input type="checkbox" className="h-4 w-4 mt-0.5 accent-[#118AC3]" checked={!!f.paid} onChange={(e) => setF({ ...f, paid: e.target.checked })} />
              <span>Paid / billed key<span className="block text-ink-muted text-[12px]">Leave unticked for a free Gemini key: your team keeps seeing the "sample data only" banner.</span></span>
            </label>
          )}
        </div>
      )}
      {isAdmin && <div className="mt-5 flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending && <Spinner />} Save</button>
        <button className="btn-outline" disabled={check.isPending || save.isPending} onClick={() => check.mutate()}>{check.isPending && <Spinner />} Test connection</button>
        {test && <span className={`text-[13px] ${test.ok ? "text-ok" : "text-fit-gap-ink"}`}>{test.message}</span>}
      </div>}
      <div className="mt-3 text-[12px] text-ink-muted">
        Keys are stored encrypted and never shown again.{cfg.updated_by ? ` Last changed by ${cfg.updated_by}.` : ""} "Test connection" checks the settings above as you've filled them in, without saving. Leave the key empty to test the saved one.
      </div>
    </section>
  );
}

/** Download everything, or delete everything. Company admins only. */
function CompanyData({ name }: { name: string }) {
  const { user, logout } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [pw, setPw] = useState("");
  const sso = !!(user as any)?.sso;
  const del = useMutation({
    mutationFn: () => api.post<any>("/company/delete", { confirm_name: confirmName, password: pw }),
    onSuccess: () => { setOpen(false); logout(); window.location.href = "/?deleted=1"; },
    onError: (e: any) => toast("error", e.message),
  });
  const exportAll = async () => {
    setBusy(true);
    try { await download("/company/export", `${name} - RevenueForge export.zip`); toast("ok", "Export downloaded."); }
    catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  return (
    <section className="card p-5">
      <div className="font-bold flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-brand-600" /> Your company's data</div>
      <div className="text-[13px] text-ink-muted mb-4">
        Everything in this workspace belongs to your company. See <a className="underline" href="/trust" target="_blank" rel="noreferrer">Trust & data</a> for
        where it's stored and which services handle it.
      </div>
      <div className="flex flex-wrap gap-3">
        <button className="btn-outline" disabled={busy} onClick={exportAll}>{busy ? <Spinner /> : <Download className="h-4 w-4" />} Download all company data</button>
        <button className="btn-ghost text-fit-gap-ink" onClick={() => { setConfirmName(""); setPw(""); setOpen(true); }}><Trash2 className="h-4 w-4" /> Delete company permanently</button>
      </div>
      <div className="text-[12px] text-ink-muted mt-2">The download is a zip with your library, every deal, comments, the audit log and all uploaded and generated files. Passwords and AI keys aren't included.</div>
      <Modal open={open} onClose={() => !del.isPending && setOpen(false)} title="Delete this company permanently">
        <form className="space-y-3 text-[13.5px]" onSubmit={(e) => { e.preventDefault(); del.mutate(); }}>
          <p>This deletes <b>{name}</b> straight away: every user's access, the knowledge library, all deals and documents, comments, the audit log,
            and every uploaded and generated file. It can't be undone. Download the company's data first if you may need it.</p>
          <p className="text-ink-muted">Copies of an RFP that a supplier already accepted stay in that supplier's workspace.</p>
          <div><label className="label" htmlFor="del-name">Type the company name to confirm</label>
            <input id="del-name" className="input" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} placeholder={name} autoComplete="off" /></div>
          <div><label className="label" htmlFor="del-pw">Your password{sso ? " (leave empty if you only sign in with Google or Microsoft)" : ""}</label>
            <input id="del-pw" className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></div>
          <div className="flex gap-3 pt-1">
            <button className="btn-primary bg-fit-gap-ink hover:bg-fit-gap-ink" disabled={del.isPending || confirmName.trim() !== name.trim()}>
              {del.isPending && <Spinner />} Delete permanently</button>
            <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      </Modal>
    </section>
  );
}
