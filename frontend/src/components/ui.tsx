import clsx from "clsx";
import { AlertCircle, CheckCircle2, FileUp, Loader2, X } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { CAT_STYLE, MATCH_LABEL, MATCH_STYLE } from "../lib/format";

export function ProductMark({ white = false }: { white?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/brand/revenueforge-mark.svg" alt="" className="h-8 w-8" />
      <div className="leading-none">
        <div className={clsx("text-[17px] font-extrabold tracking-tight", white ? "text-white" : "text-brand-900")}>
          Revenue<span className={white ? "text-ember-400" : "text-ember-500"}>Forge</span>
        </div>
        <div className={clsx("text-[10.5px] font-medium mt-0.5", white ? "text-brand-200" : "text-ink-muted")}>Deal &amp; proposal intelligence</div>
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
  const s = risk === "High" ? "bg-[#FBE7E5] text-fit-gap-ink" : risk === "Medium" ? "bg-[#FBF1DD] text-fit-partial-ink" : "bg-[#EEF1F4] text-fit-confirm-ink";
  return <span className={clsx("chip", s)}>{risk} risk</span>;
}

export function StageStatus({ status }: { status: string }) {
  const map: Record<string, string> = {
    approved: "bg-ok-bg text-ok",
    draft: "bg-brand-50 text-brand-700",
    running: "bg-ember-50 text-ember-600",
    pending: "bg-line-soft text-ink-muted",
    failed: "bg-[#FBE7E5] text-fit-gap-ink",
  };
  const label: Record<string, string> = { approved: "Approved", draft: "Ready for review", running: "Running", pending: "Waiting", failed: "Failed" };
  return <span className={clsx("chip", map[status] || map.pending)}>{label[status] || status}</span>;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center py-14 px-6 anim-fade-in">
      {icon && (
        <div className="mb-4 h-16 w-16 rounded-2xl grid place-items-center text-brand-500 bg-gradient-to-b from-brand-50 to-white border border-brand-100 shadow-[0_10px_24px_-14px_rgba(17,138,195,.6)]">
          {icon}
        </div>
      )}
      <div className="font-semibold text-[15.5px] text-ink">{title}</div>
      {children && <div className="text-sm text-ink-muted mt-1 max-w-md">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "ember" | "brand" }) {
  return (
    <div className="card card-hover px-4 py-3.5">
      <div className="text-[12.5px] text-ink-muted font-medium">{label}</div>
      <div className={clsx("num text-[26px] font-bold tracking-[-0.02em] mt-0.5", tone === "ember" ? "text-ember-600" : tone === "brand" ? "text-brand-700" : "text-ink")}>
        {value}
      </div>
      {sub && <div className="text-[12px] text-ink-muted mt-0.5">{sub}</div>}
    </div>
  );
}

/** Several headline numbers in one quiet strip instead of a row of separate cards. */
export function StatStrip({ items }: { items: { label: string; value: ReactNode; sub?: ReactNode; tone?: "ember" | "brand" | "gap" }[] }) {
  return (
    <div className="card relative overflow-hidden grid grid-cols-2 md:flex md:divide-x divide-line-soft stagger">
      <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-400/50 to-transparent" />
      {items.map((it) => (
        <div key={it.label} className="group px-5 py-5 md:flex-1 min-w-0 transition-colors duration-300 hover:bg-gradient-to-b hover:from-brand-50/60 hover:to-transparent">
          <div className="text-[12px] font-medium text-ink-muted tracking-[0.01em]">{it.label}</div>
          <div className={clsx("font-display num text-[30px] leading-tight mt-1 tracking-[-0.02em] transition-transform duration-300 ease-apple group-hover:-translate-y-px",
            it.tone === "ember" ? "text-ember-600" : it.tone === "gap" ? "text-fit-gap-ink" : "text-brand-950")}>{it.value}</div>
          {it.sub && <div className="text-[12px] text-ink-muted mt-1 leading-snug">{it.sub}</div>}
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
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-midnight-950/45 backdrop-blur-[6px] p-4 pt-[8vh] anim-fade-in" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx("card w-full shadow-float max-h-[84vh] overflow-auto scroll-thin rounded-2xl anim-scale-in", xl ? "max-w-6xl" : wide ? "max-w-3xl" : "max-w-lg")}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-line-soft sticky top-0 z-[2] bg-white/90 backdrop-blur">
          <h2 className="font-bold text-[15.5px] tracking-[-0.01em]">{title}</h2>
          <button className="btn-ghost h-8 px-2" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
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
        "rounded-xl2 border-2 border-dashed px-6 py-9 text-center cursor-pointer transition-all duration-300 ease-apple",
        over ? "border-brand-500 bg-brand-50 scale-[1.01] shadow-hover" : "border-line bg-gradient-to-b from-white to-[#FAFCFD] hover:border-brand-400 hover:shadow-card",
      )}
    >
      <input ref={ref} type="file" accept={accept} hidden onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
      <div className="flex flex-col items-center gap-2 text-sm">
        <span className="h-11 w-11 rounded-xl grid place-items-center bg-brand-50 text-brand-500 border border-brand-100">
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
          <div key={t.id} className={clsx("glass rounded-xl2 shadow-lift px-4 py-3 text-sm flex gap-2.5 items-start anim-toast-in", t.kind === "error" && "border-[#F1C4C0]")}>
            {t.kind === "ok" ? <CheckCircle2 className="h-4 w-4 text-ok mt-0.5 shrink-0" /> : <AlertCircle className="h-4 w-4 text-fit-gap-ink mt-0.5 shrink-0" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);
