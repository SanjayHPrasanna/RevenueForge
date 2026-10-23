import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { Modal, PageLoader, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
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
  const { data: aiCfg } = useQuery({ queryKey: ["ai-config"], queryFn: () => api.get("/auth/ai-config") });
  const [s, setS] = useState<any>(null);
  const [llmForm, setLlmForm] = useState({ provider: "none", api_key: "", model: "", embed_model: "gemini-embedding-001", rpm: 8, paid: false });
  const [inv, setInv] = useState(false);
  const [nu, setNu] = useState({ name: "", email: "", role: "presales", password: "" });
  useEffect(() => { if (c && !s) setS({ ...c.settings, about: c.about }); }, [c]);
  useEffect(() => {
    if (aiCfg) {
      setLlmForm({
        provider: aiCfg.provider || "none",
        api_key: "",
        model: aiCfg.model || "",
        embed_model: aiCfg.embed_model || "gemini-embedding-001",
        rpm: aiCfg.rpm || 8,
        paid: !!aiCfg.paid,
      });
    }
  }, [aiCfg]);
  const save = useMutation({
    mutationFn: () => api.put("/company", { about: s.about, settings: { target_margin: s.target_margin, min_margin: s.min_margin, travel_pct: s.travel_pct, hide_employee_names: s.hide_employee_names } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["company"] }); toast("ok", "Settings saved. New pricing runs use them."); },
    onError: (e: any) => toast("error", e.message),
  });
  const saveAi = useMutation({
    mutationFn: () => api.put("/auth/ai-config", {
      provider: llmForm.provider,
      api_key: llmForm.api_key,
      model: llmForm.model,
      embed_model: llmForm.embed_model,
      rpm: Number(llmForm.rpm),
      paid: llmForm.paid,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["company"] });
      qc.invalidateQueries({ queryKey: ["ai-config"] });
      toast("ok", "AI provider settings saved.");
    },
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
      <h1 className="font-display text-[32px] leading-tight text-brand-950">Settings</h1>
      <section className="card p-5">
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
        <div className="mt-4"><span className="label">About the company (used in proposals)</span><textarea className="input h-24 py-2" value={s.about} onChange={(e) => setS({ ...s, about: e.target.value })} disabled={!isAdmin} /></div>
        {isAdmin && <button className="btn-primary mt-4" onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending && <Spinner />} Save settings</button>}
      </section>

      <section className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="font-bold">AI engine</div>
            <div className="text-[13px] text-ink-muted">Choose the provider and enter the API key for this workspace.</div>
          </div>
          {isAdmin && <button className="btn-primary" onClick={() => saveAi.mutate()} disabled={saveAi.isPending}>{saveAi.isPending && <Spinner />} Save AI settings</button>}
        </div>

        <div className="grid md:grid-cols-2 gap-4">
          <label className="text-[13px]">
            <span className="label">Provider</span>
            <select className="input" value={llmForm.provider} onChange={(e) => setLlmForm({ ...llmForm, provider: e.target.value })} disabled={!isAdmin}>
              <option value="none">Rules engine only</option>
              <option value="gemini">Google Gemini</option>
              <option value="anthropic">Anthropic Claude</option>
              <option value="openai">OpenAI</option>
              <option value="azure">Azure OpenAI</option>
            </select>
          </label>

          <label className="text-[13px]">
            <span className="label">API key</span>
            <input className="input" type="password" placeholder={aiCfg?.api_key_present ? "Leave blank to keep the existing key" : "Paste your API key"} value={llmForm.api_key} onChange={(e) => setLlmForm({ ...llmForm, api_key: e.target.value })} disabled={!isAdmin} />
          </label>

          <label className="text-[13px]">
            <span className="label">Model</span>
            <input className="input" value={llmForm.model} onChange={(e) => setLlmForm({ ...llmForm, model: e.target.value })} disabled={!isAdmin} placeholder={llmForm.provider === "gemini" ? "gemini-2.5-flash" : llmForm.provider === "anthropic" ? "claude-sonnet-4-5" : llmForm.provider === "openai" ? "gpt-4o" : "deployment name"} />
          </label>

          <label className="text-[13px]">
            <span className="label">Embedding model</span>
            <input className="input" value={llmForm.embed_model} onChange={(e) => setLlmForm({ ...llmForm, embed_model: e.target.value })} disabled={!isAdmin} />
          </label>

          <label className="text-[13px]">
            <span className="label">Requests / minute</span>
            <input className="input num" type="number" min={1} value={llmForm.rpm} onChange={(e) => setLlmForm({ ...llmForm, rpm: Number(e.target.value) || 1 })} disabled={!isAdmin} />
          </label>

          <label className="flex items-center gap-2 text-[13.5px] pt-6">
            <input type="checkbox" className="h-4 w-4 accent-[#118AC3]" checked={!!llmForm.paid} onChange={(e) => setLlmForm({ ...llmForm, paid: e.target.checked })} disabled={!isAdmin} />
            Paid tier / billed project
          </label>
        </div>

        {!isAdmin && <div className="mt-4 text-[12.5px] text-ink-muted">Only admins can change the AI provider and keys.</div>}
      </section>

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
                  <select className="input h-9" value={u.role} disabled={!isAdmin || u.id === user?.id} onChange={(e) => role.mutate({ id: u.id, body: { role: e.target.value } })}>
                    {Object.keys(ROLE_HELP).map((r) => <option key={r} value={r} className="capitalize">{r}</option>)}
                  </select>
                </td>
                <td className="td text-[12.5px] text-ink-muted hidden md:table-cell">{ROLE_HELP[u.role]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

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
