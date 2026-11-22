/* Hand-built SVG/HTML charts for RevenueForge. One tooltip, one status palette (FIT), thin marks, 2px gaps,
   recessive axes. Every chart carries visible labels or a legend so meaning never rests on colour alone. */
import clsx from "clsx";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { FIT, money } from "../lib/format";

// ---------------------------------------------------------------- tooltip
type TipState = { x: number; y: number; content: ReactNode } | null;
const TipCtx = createContext<{ show: (e: React.MouseEvent | React.FocusEvent, c: ReactNode) => void; hide: () => void }>({ show: () => {}, hide: () => {} });

export function TipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TipState>(null);
  const show = useCallback((e: React.MouseEvent | React.FocusEvent, content: ReactNode) => {
    let x: number, y: number;
    if ("clientX" in e && e.clientX) { x = e.clientX; y = e.clientY; } else {
      const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
      x = r.left + r.width / 2; y = r.top;
    }
    setTip({ x, y, content });
  }, []);
  const hide = useCallback(() => setTip(null), []);
  const left = tip ? Math.min(Math.max(12, tip.x + 14), window.innerWidth - 332) : 0;
  const top = tip ? (tip.y > window.innerHeight - 180 ? tip.y - 150 : tip.y + 16) : 0;
  return (
    <TipCtx.Provider value={{ show, hide }}>
      {children}
      {tip && (
        <div role="tooltip" className="fixed z-[70] pointer-events-none w-[320px] rounded-[14px] glass text-ink px-3.5 py-3 text-[12.5px] leading-snug"
          style={{ left, top }}>
          {tip.content}
        </div>
      )}
    </TipCtx.Provider>
  );
}
export const useTip = () => useContext(TipCtx);

// ---------------------------------------------------------------- legend
export function FitLegend({ counts, className, onPick, active }: { counts?: Record<string, number>; className?: string; onPick?: (k: string) => void; active?: string }) {
  return (
    <div className={clsx("flex flex-wrap gap-x-4 gap-y-1.5 text-[12.5px] text-ink-soft", className)}>
      {FIT.map((f) => {
        const body = (
          <>
            <Swatch k={f.key} />
            <span>{f.label}</span>
            {counts && <span className="num font-semibold text-ink">{counts[f.key] || 0}</span>}
          </>
        );
        return onPick ? (
          <button key={f.key} onClick={() => onPick(f.key)} aria-pressed={active === f.key}
            className={clsx("inline-flex items-center gap-1.5 rounded px-1.5 -mx-1.5 py-0.5 hover:bg-line-soft", active === f.key && "bg-line-soft")}>{body}</button>
        ) : <span key={f.key} className="inline-flex items-center gap-1.5">{body}</span>;
      })}
    </div>
  );
}

export function Swatch({ k, size = 10 }: { k: string; size?: number }) {
  const f = FIT.find((x) => x.key === k) || FIT[3];
  return <span aria-hidden className="inline-block rounded-[3px] shrink-0" style={{ width: size, height: size, background: "hollow" in f ? "transparent" : f.fill, boxShadow: "hollow" in f ? `inset 0 0 0 1.5px ${f.fill}` : undefined }} />;
}

// ---------------------------------------------------------------- coverage map (the signature view)
/** Every requirement as one tile, grouped by the RFP section it came from, in document order. */
export function CoverageMap({ reqs, onPick, selected, compact = false, maxSections }: { reqs: any[]; onPick?: (r: any) => void; selected?: string; compact?: boolean; maxSections?: number }) {
  const { show, hide } = useTip();
  const groups = useMemo(() => {
    const m = new Map<string, any[]>();
    [...reqs].sort((a, b) => (a.block_idx ?? 0) - (b.block_idx ?? 0)).forEach((r) => {
      const k = (r.section || "General").replace(/\s+/g, " ").trim();
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(r);
    });
    return [...m.entries()];
  }, [reqs]);
  const shown = maxSections ? groups.slice(0, maxSections) : groups;
  const cell = compact ? 14 : 18;
  return (
    <div className={clsx("grid gap-x-6 gap-y-3.5", compact ? "grid-cols-[repeat(auto-fill,minmax(150px,1fr))]" : "grid-cols-[repeat(auto-fill,minmax(190px,1fr))]")}>
      {shown.map(([sec, rs]) => (
        <div key={sec} className="min-w-0">
          <div className="text-[11.5px] text-ink-muted truncate mb-1.5" title={sec}>{sec}</div>
          <div className="flex flex-wrap gap-[3px]">
            {rs.map((r) => {
              const f = FIT.find((x) => x.key === r.match_status) || FIT[3];
              const hollow = "hollow" in f;
              const tip = (
                <div>
                  <div className="flex items-center gap-2 mb-1"><span className="num font-semibold">{r.source_ref || r.code}</span><span className="opacity-70">p.{r.page}</span>
                    <span className="ml-auto rounded px-1.5 text-[11px] font-semibold" style={{ background: f.fill, color: "white" }}>{f.label}</span></div>
                  <div className="line-clamp-4">{r.text}</div>
                  <div className="opacity-70 mt-1">{r.category} · {r.priority}</div>
                </div>
              );
              return (
                <button key={r.id} aria-label={`${r.source_ref || r.code}: ${f.label}. ${r.text}`}
                  onMouseMove={(e) => show(e, tip)} onMouseLeave={hide} onFocus={(e) => show(e, tip)} onBlur={hide}
                  onClick={() => onPick?.(r)}
                  className={clsx("grid place-items-center rounded-[3px] transition-transform hover:scale-125 focus-visible:scale-125", selected === r.id && "outline outline-2 outline-offset-1 outline-brand-950")}
                  style={{ width: cell, height: cell }}>
                  {/* desirable requirements are drawn smaller: same colour, less weight */}
                  <span className="block rounded-[3px]" style={{ width: r.priority === "Desirable" ? cell * 0.62 : cell, height: r.priority === "Desirable" ? cell * 0.62 : cell,
                    background: hollow ? "transparent" : f.fill, boxShadow: hollow ? `inset 0 0 0 1.5px ${f.fill}` : undefined }} />
                </button>
              );
            })}
          </div>
        </div>
      ))}
      {maxSections && groups.length > maxSections && <div className="text-[12px] text-ink-muted self-end">+{groups.length - maxSections} more sections</div>}
    </div>
  );
}

// ---------------------------------------------------------------- status rows (category x match status)
export function StatusRows({ rows, onPick }: { rows: { label: string; counts: Record<string, number> }[]; onPick?: (label: string, status: string) => void }) {
  const { show, hide } = useTip();
  const max = Math.max(1, ...rows.map((r) => FIT.reduce((s, f) => s + (r.counts[f.key] || 0), 0)));
  return (
    <div className="space-y-3">
      {rows.map((r) => {
        const total = FIT.reduce((s, f) => s + (r.counts[f.key] || 0), 0);
        return (
          <div key={r.label} className="grid grid-cols-[112px_1fr_36px] items-center gap-3">
            <div className="text-[13px] text-ink-soft truncate">{r.label}</div>
            <div className="flex gap-[2px] h-[14px]" style={{ width: `${(total / max) * 100}%` }}>
              {FIT.map((f) => {
                const n = r.counts[f.key] || 0;
                if (!n) return null;
                const hollow = "hollow" in f;
                return (
                  <button key={f.key} aria-label={`${r.label}, ${f.label}: ${n}`} onClick={() => onPick?.(r.label, f.key)}
                    onMouseMove={(e) => show(e, <div><b>{r.label}</b><div>{f.label}: <span className="num font-semibold">{n}</span> of {total} ({Math.round((n / total) * 100)}%)</div></div>)} onMouseLeave={hide}
                    className="h-full first:rounded-l last:rounded-r min-w-[3px]"
                    style={{ flex: n, background: hollow ? "transparent" : f.fill, boxShadow: hollow ? `inset 0 0 0 1.5px ${f.fill}` : undefined }} />
                );
              })}
            </div>
            <div className="num text-[13px] font-semibold text-right">{total}</div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- readiness: today -> with mitigations, on a scale with verdict zones
export function ReadinessScale({ today, mitigated }: { today: number; mitigated: number }) {
  const zones = [
    // the same thresholds the bid verdict uses
    { from: 0, to: 55, label: "No bid" },
    { from: 55, to: 70, label: "Qualify" },
    { from: 70, to: 100, label: "Bid" },
  ];
  return (
    <div>
      <div className="relative h-[54px]">
        <div className="absolute inset-x-0 top-[22px] h-[10px] flex gap-[2px]">
          {zones.map((z, i) => <div key={i} className="h-full first:rounded-l last:rounded-r" style={{ flex: z.to - z.from, background: ["rgb(var(--line) / .06)", "rgb(var(--line) / .1)", "rgb(var(--line) / .15)"][i] }} />)}
        </div>
        <div className="absolute top-[26px] h-[2px] bg-brand-500" style={{ left: `${today}%`, width: `${Math.max(0, mitigated - today)}%` }} />
        <Marker at={today} label={`${today}%`} sub="Today" />
        <Marker at={mitigated} label={`${mitigated}%`} sub="With mitigations" strong />
      </div>
      <div className="flex text-[11px] text-ink-faint mt-1">
        {zones.map((z) => <div key={z.label} style={{ flex: z.to - z.from }} className="truncate pr-1">{z.label}</div>)}
      </div>
    </div>
  );
}
function Marker({ at, label, sub, strong }: { at: number; label: string; sub: string; strong?: boolean }) {
  return (
    <div className="absolute top-0 -translate-x-1/2 flex flex-col items-center" style={{ left: `${at}%` }}>
      <div className={clsx("num text-[12px] font-bold leading-none whitespace-nowrap", strong ? "text-brand-950" : "text-ink-muted")}>{label}</div>
      <div className={clsx("mt-[6px] h-[14px] w-[14px] rounded-full border-2 border-white", strong ? "bg-brand-500" : "bg-ink-faint")} />
      <div className="sr-only">{sub}</div>
    </div>
  );
}

// ---------------------------------------------------------------- simple horizontal bars (one series, one colour)
export function Bars({ rows, unit = "", color = "rgb(var(--fit-strong))", format, onPick, highlight }: {
  rows: { label: string; value: number; sub?: string; tip?: ReactNode }[]; unit?: string; color?: string; format?: (v: number) => string;
  onPick?: (label: string) => void; highlight?: string;
}) {
  const { show, hide } = useTip();
  const max = Math.max(1, ...rows.map((r) => r.value));
  const fmt = format || ((v: number) => `${Math.round(v).toLocaleString()}${unit}`);
  return (
    <div className="space-y-2.5">
      {rows.map((r) => (
        <div key={r.label} className={clsx("grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 items-baseline", onPick && "cursor-pointer")} onClick={() => onPick?.(r.label)}
          onMouseMove={(e) => r.tip && show(e, r.tip)} onMouseLeave={hide}>
          <div className={clsx("text-[13px] truncate", highlight === r.label ? "font-semibold text-ink" : "text-ink-soft")}>{r.label}{r.sub && <span className="text-ink-faint"> {r.sub}</span>}</div>
          <div className="num text-[12.5px] font-semibold text-right">{fmt(r.value)}</div>
          <div className="col-span-2 h-[6px] rounded-full bg-line-soft mt-1">
            <div className="h-full rounded-full" style={{ width: `${Math.max(1.5, (r.value / max) * 100)}%`, background: highlight && highlight !== r.label ? "rgb(var(--b400) / .45)" : color }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- price ladder: cost, margin floor, scenarios on one scale
export function PriceLadder({ cost, floorMargin, scenarios, selected, list, fmt, onPick }: {
  cost: number; floorMargin: number; scenarios: { name: string; price: number; margin_pct: number }[]; selected: string; list?: number;
  fmt: (v: number) => string; onPick?: (name: string) => void;
}) {
  const { show, hide } = useTip();
  const floor = cost / (1 - floorMargin / 100);
  const hi = Math.max(list || 0, ...scenarios.map((s) => s.price)) * 1.06;
  const lo = cost * 0.82;
  const X = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const sorted = [...scenarios].sort((a, b) => a.price - b.price);
  return (
    <div className="pt-1">
      <div className="relative h-[118px]">
        {/* below-floor zone */}
        <div className="absolute top-[58px] h-[14px] rounded-l bg-fit-gap-soft" style={{ left: 0, width: `${X(floor)}%` }} />
        <div className="absolute top-[58px] h-[14px] rounded-r bg-paper" style={{ left: `${X(floor)}%`, right: 0 }} />
        {/* cost line */}
        <div className="absolute top-[44px] bottom-[18px] w-[2px] bg-ink" style={{ left: `${X(cost)}%` }} />
        <div className="absolute bottom-0 -translate-x-1/2 text-[11.5px] text-ink whitespace-nowrap" style={{ left: `${X(cost)}%` }}>Cost <span className="num font-semibold">{fmt(cost)}</span></div>
        {/* floor */}
        <div className="absolute top-[50px] bottom-[18px] w-0 border-l-2 border-dashed border-fit-gap" style={{ left: `${X(floor)}%` }} />
        <div className="absolute top-[78px] translate-x-1.5 text-[11px] text-fit-gap-ink whitespace-nowrap" style={{ left: `${X(floor)}%` }}>{floorMargin}% margin floor</div>
        {/* scenarios */}
        {sorted.map((s, i) => {
          const active = s.name === selected;
          const above = i % 2 === 0;
          return (
            <button key={s.name} onClick={() => onPick?.(s.name)} aria-label={`${s.name}: ${fmt(s.price)} at ${s.margin_pct}% margin`}
              onMouseMove={(e) => show(e, <div><b>{s.name}</b><div className="num">{fmt(s.price)} · {s.margin_pct}% margin</div><div className="opacity-70">Gross profit {fmt(s.price - cost)}</div></div>)} onMouseLeave={hide}
              className="absolute -translate-x-1/2 flex flex-col items-center group" style={{ left: `${X(s.price)}%`, top: above ? 0 : 30 }}>
              <span className={clsx("text-[12px] whitespace-nowrap leading-tight", active ? "font-bold text-brand-950" : "text-ink-soft group-hover:text-ink")}>{s.name}</span>
              <span className={clsx("num text-[11.5px] whitespace-nowrap leading-tight", active ? "text-ember-600 font-semibold" : "text-ink-muted")}>{fmt(s.price)}</span>
              <span className="w-px bg-line" style={{ height: above ? 30 : 0 }} />
              <span className={clsx("rounded-full border-2 border-white shadow", active ? "h-[18px] w-[18px] bg-ember-500" : "h-[13px] w-[13px] bg-brand-500")} style={{ marginTop: above ? 0 : 2 }} />
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- waterfall: labour -> travel -> contingency -> cost -> margin -> price
export function Waterfall({ steps, fmt }: { steps: { label: string; value: number; kind: "add" | "total" | "margin" }[]; fmt: (v: number) => string }) {
  const { show, hide } = useTip();
  const W = 640, H = 260, padL = 8, padB = 36, padT = 22;
  let run = 0;
  const bars = steps.map((s) => {
    const start = s.kind === "total" ? 0 : run;
    const end = s.kind === "total" ? s.value : run + s.value;
    if (s.kind !== "total") run = end; else run = s.value;
    return { ...s, start, end };
  });
  const max = Math.max(...bars.map((b) => b.end)) * 1.08;
  const bw = (W - padL * 2) / steps.length;
  const Y = (v: number) => padT + (1 - v / max) * (H - padT - padB);
  const fill = (k: string) => (k === "total" ? "rgb(var(--b500))" : k === "margin" ? "rgb(var(--e500))" : "rgb(var(--b400) / .6)");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={steps.map((s) => `${s.label} ${fmt(s.value)}`).join(", ")}>
      <line x1={padL} x2={W - padL} y1={H - padB} y2={H - padB} style={{ stroke: "rgb(var(--line) / .16)" }} />
      {bars.map((b, i) => {
        const x = padL + i * bw + bw * 0.18, w = bw * 0.64;
        const y0 = Y(Math.max(b.start, b.end)), y1 = Y(Math.min(b.start, b.end));
        return (
          <g key={b.label} onMouseMove={(e) => show(e, <div><b>{b.label}</b><div className="num">{fmt(b.value)}</div></div>)} onMouseLeave={hide}>
            {i > 0 && <line x1={padL + (i - 1) * bw + bw * 0.82} x2={x} y1={Y(bars[i - 1].end)} y2={Y(bars[i - 1].end)} strokeWidth={1} style={{ stroke: "rgb(var(--line) / .3)" }} />}
            <rect x={x} y={y0} width={w} height={Math.max(2, y1 - y0)} rx={3} fill={fill(b.kind)} />
            <text x={x + w / 2} y={y0 - 6} textAnchor="middle" fontSize={11.5} fontWeight={600} className="num" style={{ fill: "rgb(var(--ink))" }}>{fmt(b.value)}</text>
            <text x={x + w / 2} y={H - padB + 16} textAnchor="middle" fontSize={11.5} style={{ fill: "rgb(var(--muted))" }}>{b.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------- gantt on a month axis
export function Gantt({ phases, months, milestones = [] }: { phases: { name: string; detail?: string; start: number; end: number }[]; months: number; milestones?: { label: string; at: number }[] }) {
  const { show, hide } = useTip();
  const step = months > 24 ? 6 : months > 12 ? 3 : 1;
  const ticks = Array.from({ length: Math.floor(months / step) + 1 }, (_, i) => i * step);
  const X = (m: number) => `${(m / Math.max(1, months)) * 100}%`;
  return (
    <div className="grid grid-cols-[minmax(120px,210px)_1fr] gap-x-4">
      <div />
      <div className="relative h-5 text-[11px] text-ink-faint">
        {ticks.map((t) => <span key={t} className="absolute -translate-x-1/2 num" style={{ left: X(t) }}>{t === 0 ? "Start" : `M${t}`}</span>)}
      </div>
      {phases.map((p) => (
        <div key={p.name} className="contents">
          <div className="py-2 min-w-0"><div className="text-[13px] font-semibold truncate">{p.name}</div>{p.detail && <div className="text-[11.5px] text-ink-muted truncate">{p.detail}</div>}</div>
          <div className="relative border-l border-line">
            {ticks.map((t) => <span key={t} className="absolute top-0 bottom-0 w-px bg-line-soft" style={{ left: X(t) }} />)}
            <div className="absolute top-1/2 -translate-y-1/2 h-[12px] rounded-full bg-brand-500"
              onMouseMove={(e) => show(e, <div><b>{p.name}</b><div className="num">Month {Math.round(p.start * 10) / 10} to {Math.round(p.end * 10) / 10}</div>{p.detail && <div className="opacity-70">{p.detail}</div>}</div>)} onMouseLeave={hide}
              style={{ left: X(p.start), width: `max(10px, ${((p.end - p.start) / Math.max(1, months)) * 100}%)` }} />
          </div>
        </div>
      ))}
      {milestones.length > 0 && (
        <>
          <div className="pt-2 text-[12px] text-ink-muted">Payment milestones</div>
          <div className="relative h-8 mt-2 border-l border-line">
            {milestones.map((m) => (
              <span key={m.label} className="absolute top-1 -translate-x-1/2 h-3 w-3 rotate-45 bg-ember-500" style={{ left: X(m.at) }}
                onMouseMove={(e) => show(e, <div><b>{m.label}</b><div className="num">Month {m.at}</div></div>)} onMouseLeave={hide} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- team: FTE per role, onsite vs offshore
export function TeamBars({ team }: { team: { role: string; fte: number; location: string; unfilled?: number }[] }) {
  const { show, hide } = useTip();
  const byRole = new Map<string, { on: number; off: number; open: number }>();
  team.forEach((t) => {
    const r = byRole.get(t.role) || { on: 0, off: 0, open: 0 };
    if (/onsite/i.test(t.location)) r.on += t.fte; else r.off += t.fte;
    r.open += t.unfilled || 0;
    byRole.set(t.role, r);
  });
  const rows = [...byRole.entries()].sort((a, b) => b[1].on + b[1].off - (a[1].on + a[1].off));
  const max = Math.max(1, ...rows.map(([, r]) => r.on + r.off));
  return (
    <div>
      <div className="flex gap-4 text-[12px] text-ink-soft mb-3">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-[3px] bg-brand-500" />Onsite</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-[3px] bg-brand-200" />Offshore</span>
      </div>
      <div className="space-y-2">
        {rows.map(([role, r]) => (
          <div key={role} className="grid grid-cols-[minmax(0,150px)_1fr_40px] gap-3 items-center"
            onMouseMove={(e) => show(e, <div><b>{role}</b><div className="num">{r.on + r.off} FTE: {r.on} onsite, {r.off} offshore</div>{r.open > 0 && <div>{r.open} still to hire</div>}</div>)} onMouseLeave={hide}>
            <div className="text-[13px] text-ink-soft truncate">{role}</div>
            <div className="flex gap-[2px] h-[12px]" style={{ width: `${((r.on + r.off) / max) * 100}%` }}>
              {r.on > 0 && <div className="h-full rounded-l bg-brand-500 last:rounded-r" style={{ flex: r.on }} />}
              {r.off > 0 && <div className="h-full rounded-r bg-brand-200 first:rounded-l" style={{ flex: r.off }} />}
            </div>
            <div className="num text-[12.5px] font-semibold text-right">{r.on + r.off}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- weights (parts of a whole, labelled directly)
export function WeightBar({ items }: { items: { label: string; weight: number }[] }) {
  const { show, hide } = useTip();
  const total = items.reduce((s, i) => s + i.weight, 0) || 1;
  const shades = ["rgb(var(--b500))", "rgb(var(--b500) / .8)", "rgb(var(--fit-strong))", "rgb(var(--b400) / .7)", "rgb(var(--b400) / .45)", "rgb(var(--b400) / .25)"];
  return (
    <div>
      <div className="flex gap-[2px] h-[14px]">
        {items.map((it, i) => (
          <div key={it.label} className="h-full first:rounded-l last:rounded-r" style={{ flex: it.weight, background: shades[Math.min(i, shades.length - 1)] }}
            onMouseMove={(e) => show(e, <div><b>{it.label}</b><div className="num">{it.weight}% of the score</div></div>)} onMouseLeave={hide} />
        ))}
      </div>
      <ol className="mt-3 space-y-1.5">
        {items.map((it, i) => (
          <li key={it.label} className="flex items-center gap-2.5 text-[13px]">
            <span className="h-2.5 w-2.5 rounded-[3px] shrink-0" style={{ background: shades[Math.min(i, shades.length - 1)] }} />
            <span className="text-ink-soft flex-1 min-w-0 truncate">{it.label}</span>
            <span className="num font-semibold">{Math.round((it.weight / total) * 100)}%</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------- donut-free share bar with direct labels
export function ShareBar({ parts, fmt }: { parts: { label: string; value: number; color: string }[]; fmt?: (v: number) => string }) {
  const { show, hide } = useTip();
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  return (
    <div>
      <div className="flex gap-[2px] h-[12px]">
        {parts.filter((p) => p.value > 0).map((p) => (
          <div key={p.label} className="h-full first:rounded-l last:rounded-r" style={{ flex: p.value, background: p.color }}
            onMouseMove={(e) => show(e, <div><b>{p.label}</b><div className="num">{fmt ? fmt(p.value) : p.value} ({Math.round((p.value / total) * 100)}%)</div></div>)} onMouseLeave={hide} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[12px] text-ink-soft">
        {parts.filter((p) => p.value > 0).map((p) => (
          <span key={p.label} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: p.color }} />{p.label}<span className="num font-semibold text-ink">{fmt ? fmt(p.value) : p.value}</span></span>
        ))}
      </div>
    </div>
  );
}

export const fmtMoney = (ccy: string, fx = 1) => (v: number) => money(v * fx, ccy);

// small hook: remembers which element a chart click picked, for linking chart -> list
export function useScrollTo() {
  const ref = useRef<HTMLDivElement>(null);
  return { ref, go: () => ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }) };
}
