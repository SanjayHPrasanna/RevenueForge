import clsx from "clsx";
import { AlertCircle, CheckCircle2, FileUp, Loader2, X } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { CAT_STYLE, MATCH_LABEL, MATCH_STYLE } from "../lib/format";

export function ProductMark({ white = false }: { white?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/brand/revenueforge-mark.png" alt="" className="h-8 w-8" />
      <div className="leading-none">
        <div className={clsx("text-[15px] font-bold tracking-[-0.01em]", white ? "text-white" : "text-ink")}>RevenueForge</div>
        <div className={clsx("text-[11px] font-medium mt-0.5", white ? "text-white/60" : "text-ink-muted")}>Deal &amp; proposal intelligence</div>
      </div>
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <Loader2 className={clsx("animate-spin", className)} aria-hidden />;
}

export function PageLoader({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-24 text-ink-muted text-sm anim-fade-in">
      <Spinner className="h-4 w-4 text-brand-500" /> {label}
    </div>
  );
}

export function MatchChip({ status }: { status?: string }) {
  if (!status) return null;
  return <span className={clsx("chip", MATCH_STYLE[status])}>{MATCH_LABEL[status] || status}</span>;
}

export function CatChip({ cat }: { cat: string }) {
  return <span className={clsx("chip", CAT_STYLE[cat] || "bg-line-soft text-ink-soft")}>{cat}</span>;
}

export function RiskChip({ risk }: { risk?: string }) {
  if (!risk) return null;
  const s = risk === "High" ? "bg-fit-gap-soft text-fit-gap-ink" : risk === "Medium" ? "bg-fit-partial-soft text-fit-partial-ink" : "bg-fit-confirm-soft text-fit-confirm-ink";
  return <span className={clsx("chip", s)}>{risk} risk</span>;
}

export function StageStatus({ status }: { status: string }) {
  const map: Record<string, string> = {
    approved: "bg-ok-bg text-ok",
    draft: "bg-brand-50 text-brand-700",
    running: "bg-ember-50 text-ember-600",
    pending: "bg-line-soft text-ink-muted",
    failed: "bg-fit-gap-soft text-fit-gap-ink",
  };
  const label: Record<string, string> = { approved: "Approved", draft: "Ready for review", running: "Running", pending: "Waiting", failed: "Failed" };
  return <span className={clsx("chip", map[status] || map.pending)}>{label[status] || status}</span>;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center py-14 px-6 anim-fade-in">
      {icon && (
        <div className="mb-4 h-14 w-14 rounded-[18px] grid place-items-center text-brand-600 bg-brand-500/[.12] shadow-[inset_0_0_0_1px_rgb(var(--b500)/.2)]">
          {icon}
        </div>
      )}
      <div className="font-semibold text-[14px] text-ink">{title}</div>
      {children && <div className="text-sm text-ink-muted mt-1 max-w-md">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "ember" | "brand" }) {
  return (
    <div className="card px-5 py-4">
      <div className="text-[12.5px] text-ink-muted font-semibold">{label}</div>
      <div className={clsx("num text-[22px] font-semibold tracking-[-0.01em] mt-2 leading-tight", tone === "ember" ? "text-ember-600" : tone === "brand" ? "text-brand-700" : "text-ink")}>
        {value}
      </div>
      {sub && <div className="text-[12px] text-ink-muted mt-0.5">{sub}</div>}
    </div>
  );
}

// soft tinted tiles for headline numbers, one hue each, as in the reference's KPI row
const TILE = ["kpi-1", "kpi-2", "kpi-3", "kpi-4"];

/** Headline numbers as a row of tinted tiles. */
export function StatStrip({ items }: { items: { label: string; value: ReactNode; sub?: ReactNode; tone?: "ember" | "brand" | "gap" }[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-4 stagger">
      {items.map((it, i) => (
        <div key={it.label} className={clsx("card px-5 pt-4 pb-4 min-w-0 min-h-[112px] flex flex-col", TILE[i % TILE.length])}>
          <div className="text-[12.5px] font-semibold text-ink-muted">{it.label}</div>
          <div className={clsx("num text-[22px] font-semibold leading-tight mt-2.5 tracking-[-0.01em]",
            it.tone === "ember" ? "text-ember-600" : it.tone === "gap" ? "text-fit-gap-ink" : "text-ink")}>{it.value}</div>
          {it.sub && <div className="text-[12px] text-ink-muted mt-auto pt-2 leading-snug">{it.sub}</div>}
        </div>
      ))}
    </div>
  );
}

export function Meter({ value, className }: { value: number; className?: string }) {
  const v = Math.max(0, Math.min(100, value));
  const color = v >= 70 ? "bg-ok" : v >= 50 ? "bg-fit-partial" : "bg-fit-gap";
  return (
    <div className={clsx("h-1.5 rounded-full bg-line-soft overflow-hidden", className)} role="meter" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}>
      <div className={clsx("h-full rounded-full transition-[width] duration-700 ease-apple", color)} style={{ width: `${v}%` }} />
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide, xl }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean; xl?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/45 backdrop-blur-[6px] p-4 pt-[8vh] anim-fade-in" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx("glass w-full max-h-[84vh] overflow-auto scroll-thin rounded-3xl anim-scale-in", xl ? "max-w-6xl" : wide ? "max-w-3xl" : "max-w-lg")}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-line-soft sticky top-0 z-[2] bg-[var(--panel)] backdrop-blur">
          <h2 className="font-semibold text-[17px] tracking-[-0.015em]">{title}</h2>
          <button className="btn-ghost h-8 px-2" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}

export function Dropzone({
  accept,
  onFile,
  busy,
  hint,
  label = "Drop a file here or browse",
}: {
  accept: string;
  onFile: (f: File) => void;
  busy?: boolean;
  hint?: string;
  label?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f && !busy) onFile(f);
      }}
      onClick={() => !busy && ref.current?.click()}
      onKeyDown={(e) => e.key === "Enter" && ref.current?.click()}
      role="button"
      tabIndex={0}
      className={clsx(
        "rounded-2xl border-[1.5px] border-dashed px-6 py-10 text-center cursor-pointer transition-all duration-300 ease-apple",
        over ? "border-brand-500 bg-brand-500/[.08] scale-[1.01]" : "border-ink/20 bg-ink/[.02] hover:border-brand-400 hover:bg-brand-500/[.04]",
      )}
    >
      <input ref={ref} type="file" accept={accept} hidden onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
      <div className="flex flex-col items-center gap-2 text-sm">
        <span className="h-11 w-11 rounded-[14px] grid place-items-center bg-brand-500/[.12] text-brand-600">
          {busy ? <Spinner className="h-5 w-5" /> : <FileUp className="h-5 w-5" />}
        </span>
        <div className="font-semibold text-ink">{busy ? "Reading the file…" : label}</div>
        {hint && <div className="text-ink-muted text-[12.5px]">{hint}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- toasts
type Toast = { id: number; kind: "ok" | "error"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-[min(380px,calc(100vw-2rem))]" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={clsx("glass rounded-xl2 shadow-lift px-4 py-3 text-sm flex gap-2.5 items-start anim-toast-in", t.kind === "error" && "border-fit-gap/30")}>
            {t.kind === "ok" ? <CheckCircle2 className="h-4 w-4 text-ok mt-0.5 shrink-0" /> : <AlertCircle className="h-4 w-4 text-fit-gap-ink mt-0.5 shrink-0" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);
