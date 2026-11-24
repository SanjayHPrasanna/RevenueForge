import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ago } from "../lib/format";
import { api } from "../lib/api";
import { Modal, Spinner, useToast } from "./ui";

/* Settings → AI assistants: the MCP address to give Claude or Glean, the assistants connected as this person,
   and personal API keys for tools that take a fixed key. */

type Data = {
  url: string;
  connections: { id: string; client: string; connected_at: string; last_used_at: string | null }[];
  keys: { id: string; label: string; hint: string; created_at: string; last_used_at: string | null }[];
};

export default function AiAssistants() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["mcp"], queryFn: () => api.get<Data>("/mcp/connections") });
  const [label, setLabel] = useState("Glean");
  const [making, setMaking] = useState(false);
  const [newKey, setNewKey] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<{ key: string }>("/mcp/keys", { label }),
    onSuccess: (r) => { setMaking(false); setNewKey(r.key); qc.invalidateQueries({ queryKey: ["mcp"] }); },
    onError: (e: any) => toast("error", e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/mcp/connections/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mcp"] }); toast("ok", "Disconnected. It can't reach your workspace any more."); },
    onError: (e: any) => toast("error", e.message),
  });
  const copy = (t: string, what: string) => { navigator.clipboard?.writeText(t).then(() => toast("ok", `${what} copied.`), () => toast("error", "Couldn't copy. Select and copy it instead.")); };
  if (!data) return null;
  const used = (d: string | null) => (d ? `used ${ago(d)}` : "not used yet");

  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <Bot className="h-5 w-5 text-brand-600 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="font-bold">AI assistants (Claude, Glean)</div>
          <div className="text-[13px] text-ink-muted">Ask about your deals and library from Claude or Glean. An assistant acts as you, with your role, and sees only this company.</div>
        </div>
      </div>

      <label className="label mt-4">Server address (MCP)</label>
      <div className="flex gap-2">
        <input className="input num flex-1 min-w-0" readOnly value={data.url} onFocus={(e) => e.target.select()} aria-label="MCP server address" />
        <button className="btn-outline" onClick={() => copy(data.url, "Address")}><Copy className="h-4 w-4" /> Copy</button>
      </div>
      <div className="grid md:grid-cols-2 gap-3 mt-3 text-[12.5px] text-ink-soft">
        <div className="rounded-lg border border-line-soft p-3">
          <div className="font-semibold text-ink mb-1">Claude</div>
          Settings → Connectors → Add custom connector. Paste the address, leave the OAuth fields empty, then sign in here and press Allow.
          In Claude Code: <span className="num">claude mcp add --transport http revenueforge {data.url}</span>
        </div>
        <div className="rounded-lg border border-line-soft p-3">
          <div className="font-semibold text-ink mb-1">Glean</div>
          Admin → Platform → Actions/Tools → Add remote MCP server. Paste the address and choose Dynamic client registration
          (each person signs in), or API key with a key made below.
        </div>
      </div>

      <div className="mt-5 font-semibold text-[13.5px]">Connected assistants</div>
      {data.connections.length === 0 ? <div className="text-[13px] text-ink-muted mt-1">None yet.</div> : (
        <ul className="mt-1 divide-y divide-line-soft">
          {data.connections.map((c) => (
            <li key={c.id} className="flex items-center gap-3 py-2 text-[13.5px]">
              <span className="font-medium">{c.client}</span>
              <span className="text-ink-muted text-[12.5px]">connected {ago(c.connected_at)} · {used(c.last_used_at)}</span>
              <span className="flex-1" />
              <button className="btn-ghost h-8 text-[13px]" disabled={remove.isPending} onClick={() => remove.mutate(c.id)}><Trash2 className="h-3.5 w-3.5" /> Disconnect</button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-5 flex items-center">
        <div className="font-semibold text-[13.5px]">API keys</div>
        <span className="flex-1" />
        <button className="btn-outline h-8 text-[13px]" onClick={() => setMaking(true)}><Plus className="h-3.5 w-3.5" /> New key</button>
      </div>
      <div className="text-[12.5px] text-ink-muted">For tools that take a fixed key instead of signing in. Send it as <span className="num">Authorization: Bearer &lt;key&gt;</span>.</div>
      {data.keys.length > 0 && (
        <ul className="mt-1 divide-y divide-line-soft">
          {data.keys.map((k) => (
            <li key={k.id} className="flex items-center gap-3 py-2 text-[13.5px]">
              <KeyRound className="h-4 w-4 text-ink-faint" />
              <span className="font-medium">{k.label}</span>
              <span className="num text-ink-muted text-[12.5px]">…{k.hint}</span>
              <span className="text-ink-muted text-[12.5px]">made {ago(k.created_at)} · {used(k.last_used_at)}</span>
              <span className="flex-1" />
              <button className="btn-ghost h-8 text-[13px]" disabled={remove.isPending} onClick={() => remove.mutate(k.id)}><Trash2 className="h-3.5 w-3.5" /> Revoke</button>
            </li>
          ))}
        </ul>
      )}

      <Modal open={making} onClose={() => setMaking(false)} title="New API key">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <div><label className="label">What is it for?</label><input className="input" maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} required /></div>
          <p className="text-[12.5px] text-ink-muted">The key acts as you. Anyone who has it can read this workspace as you until you revoke it.</p>
          <button className="btn-primary" disabled={create.isPending}>{create.isPending && <Spinner />} Make key</button>
        </form>
      </Modal>
      <Modal open={!!newKey} onClose={() => setNewKey("")} title="Copy your key now">
        <p className="text-[13px] text-ink-soft mb-3">This is the only time it is shown. Store it in the tool that will use it.</p>
        <div className="flex gap-2">
          <input className="input num flex-1 min-w-0" readOnly value={newKey} onFocus={(e) => e.target.select()} aria-label="New API key" />
          <button className="btn-outline" onClick={() => copy(newKey, "Key")}><Copy className="h-4 w-4" /> Copy</button>
        </div>
        <button className="btn-primary mt-4" onClick={() => setNewKey("")}>Done</button>
      </Modal>
    </section>
  );
}
