import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Network, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { Empty, PageLoader } from "../components/ui";
import { api } from "../lib/api";

// Fixed categorical order (validated reference palette); never cycled.
const TYPES: { key: string; label: string; color: string }[] = [
  { key: "Requirement", label: "Requirement", color: "#2a78d6" },
  { key: "Capability", label: "Capability", color: "#eb6834" },
  { key: "Technology", label: "Technology", color: "#1baf7a" },
  { key: "Skill", label: "Skill", color: "#eda100" },
  { key: "CaseStudy", label: "Case study", color: "#e87ba4" },
  { key: "Architecture", label: "Architecture", color: "#008300" },
  { key: "Resource", label: "Resource", color: "#6250d6" },
  { key: "Cost", label: "Cost", color: "#e34948" },
  { key: "Accelerator", label: "Accelerator", color: "#8A99A3" },
  { key: "Certification", label: "Certification", color: "#8A99A3" },
  { key: "Deal", label: "Deal", color: "#10222E" },
];
const COLOR = Object.fromEntries(TYPES.map((t) => [t.key, t.color]));

export default function GraphPage() {
  const { data: deals } = useQuery({ queryKey: ["deals"], queryFn: () => api.get("/deals") });
  const [dealId, setDealId] = useState("");
  const [hidden, setHidden] = useState<Set<string>>(new Set(["Cost", "Requirement"]));
  const fg = useRef<any>(null);
  useEffect(() => { setHidden(new Set(dealId ? ["Cost"] : ["Cost", "Requirement"])); }, [dealId]);
  useEffect(() => { fg.current?.d3Force?.("charge")?.strength(-70); }, [fg.current]);
  const [sel, setSel] = useState<string | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["graph", dealId], queryFn: () => api.get(`/graph${dealId ? `?deal_id=${dealId}` : ""}`) });
  const { data: detail } = useQuery({ queryKey: ["node", sel], queryFn: () => api.get(`/graph/node?key=${encodeURIComponent(sel!)}`), enabled: !!sel });
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: Math.max(480, e.contentRect.height) }));
    if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);
  const gd = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const nodes = data.nodes.filter((n: any) => !hidden.has(n.type)).map((n: any) => ({ ...n }));
    const ids = new Set(nodes.map((n: any) => n.id));
    return { nodes, links: data.edges.filter((e: any) => ids.has(e.source) && ids.has(e.target)).map((e: any) => ({ ...e })) };
  }, [data, hidden]);

  return (
    <div className="px-4 lg:px-8 py-6 max-w-[1500px]">
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <div>
          <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Knowledge graph</h1>
          <p className="text-ink-muted text-sm mt-0.5">How your requirements, capabilities, technologies, skills, references, architecture, people and costs connect. It grows with every deal.</p>
        </div>
        <div className="flex-1" />
        <select className="input h-9 w-auto max-w-[320px]" value={dealId} onChange={(e) => { setDealId(e.target.value); setSel(null); }} aria-label="Focus on a deal">
          <option value="">Whole company</option>
          {(deals || []).map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {TYPES.map((t) => {
          const n = data?.counts?.[t.key] || 0;
          const off = hidden.has(t.key);
          return (
            <button key={t.key} disabled={!n} onClick={() => { const s = new Set(hidden); off ? s.delete(t.key) : s.add(t.key); setHidden(s); }}
              className={clsx("chip border h-7 px-2.5 text-[12px]", off || !n ? "bg-white border-line text-ink-faint" : "bg-white border-line text-ink")}>
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: off || !n ? "#DCE3E8" : t.color }} />{t.label} <span className="num text-ink-muted">{n}</span>
            </button>
          );
        })}
      </div>
      <div className="grid lg:grid-cols-[minmax(0,1fr)_320px] gap-4">
        <div ref={wrap} className="card overflow-hidden h-[calc(100vh-240px)] min-h-[480px] bg-[#FBFCFD]">
          {isLoading ? <PageLoader /> : gd.nodes.length === 0 ? (
            <Empty icon={<Network className="h-8 w-8" />} title="The graph is empty">Import your company pack in the Knowledge library to build it.</Empty>
          ) : (
            <ForceGraph2D
              ref={fg}
              graphData={gd}
              onEngineStop={() => fg.current?.zoomToFit(400, 40)}
              width={size.w}
              height={size.h}
              backgroundColor="#FBFCFD"
              nodeRelSize={4}
              nodeVal={(n: any) => (n.type === "Deal" ? 10 : 1 + Math.min(6, n.degree / 3))}
              nodeColor={(n: any) => (sel && n.id !== sel ? COLOR[n.type] + "55" : COLOR[n.type])}
              linkColor={(l: any) => (sel && (l.source.id === sel || l.target.id === sel) ? "#118AC3" : "#C9D3DA")}
              linkWidth={(l: any) => (sel && (l.source.id === sel || l.target.id === sel) ? 1.6 : 0.6)}
              cooldownTicks={120}
              onNodeClick={(n: any) => setSel(n.id)}
              onBackgroundClick={() => setSel(null)}
              nodeLabel={(n: any) => `${n.type}: ${n.label}`}
              nodeCanvasObjectMode={() => "after"}
              nodeCanvasObject={(n: any, ctx, scale) => {
                const show = n.type === "Deal" || n.degree >= 14 || n.id === sel || scale > 2.6;
                if (!show) return;
                const label = n.label.length > 34 ? n.label.slice(0, 32) + "…" : n.label;
                ctx.font = `${n.type === "Deal" ? 600 : 500} ${11 / scale}px Hanken Grotesk, sans-serif`;
                ctx.fillStyle = "#3D4F5B";
                ctx.textAlign = "center";
                ctx.fillText(label, n.x, n.y + (n.type === "Deal" ? 16 : 9) / scale + 4);
              }}
            />
          )}
        </div>
        <aside className="card p-5 h-fit">
          {!sel || !detail ? (
            <div className="text-sm text-ink-muted">
              <div className="font-bold text-ink text-[15px] mb-2">Explore</div>
              Click any node to see what it connects to. Focus on a deal to see the path from its requirements to your capabilities, people and costs.
              <div className="mt-4 num text-[13px] text-ink-soft">{data?.totals?.nodes ?? 0} nodes · {data?.totals?.edges ?? 0} connections in total</div>
            </div>
          ) : (
            <div>
              <div className="flex items-start gap-2">
                <span className="h-3 w-3 rounded-full mt-1.5 shrink-0" style={{ background: COLOR[detail.type] }} />
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] text-ink-muted">{TYPES.find((t) => t.key === detail.type)?.label}</div>
                  <div className="font-bold leading-snug">{detail.label}</div>
                </div>
                <button className="btn-ghost h-7 px-1.5" onClick={() => setSel(null)} aria-label="Close"><X className="h-4 w-4" /></button>
              </div>
              {Object.keys(detail.props || {}).filter((k) => !["id", "deal_id"].includes(k)).length > 0 && (
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[12.5px]">
                  {Object.entries(detail.props).filter(([k]) => !["id", "deal_id"].includes(k)).map(([k, v]: any) => (
                    <div key={k} className="contents"><dt className="text-ink-muted capitalize">{k.replace(/_/g, " ")}</dt><dd className="num text-ink truncate">{String(v)}</dd></div>
                  ))}
                </dl>
              )}
              <div className="mt-4 text-[12.5px] font-semibold text-ink-soft">{detail.links.length} connections</div>
              <ul className="mt-2 space-y-1 max-h-[50vh] overflow-auto scroll-thin">
                {detail.links.map((l: any, i: number) => (
                  <li key={i}>
                    <button className="w-full text-left text-[12.5px] rounded px-2 py-1 hover:bg-paper flex gap-2" onClick={() => setSel(l.id)}>
                      <span className="h-2 w-2 rounded-full mt-1.5 shrink-0" style={{ background: COLOR[l.type] }} />
                      <span className="min-w-0"><span className="text-ink-muted">{l.rel.replace(/_/g, " ")} · </span><span className="text-ink">{l.label}</span></span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
