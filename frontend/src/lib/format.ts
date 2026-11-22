export function money(v: number | null | undefined, ccy = "USD", compact = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (compact && Math.abs(v) >= 1_000_000) return `${ccy} ${(v / 1_000_000).toFixed(2)}M`;
  if (compact && Math.abs(v) >= 10_000) return `${ccy} ${Math.round(v / 1000).toLocaleString()}K`;
  return `${ccy} ${Math.round(v).toLocaleString()}`;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v)}%`;
}

export function ago(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export const ENGAGEMENT: Record<string, string> = {
  managed_services: "Managed services",
  build_run: "Build + managed service",
  implementation: "Implementation",
  product: "Product + integration",
  consulting: "Advisory",
};

export const STAGES = [
  { key: "requirements", label: "Requirements", short: "Requirements", role: "Pre-sales" },
  { key: "matching", label: "Capability match", short: "Match", role: "Pre-sales" },
  { key: "gaps", label: "Gaps & risks", short: "Gaps", role: "Pre-sales" },
  { key: "architecture", label: "Architecture", short: "Architecture", role: "Architect" },
  { key: "estimation", label: "Effort & team", short: "Effort", role: "Architect" },
  { key: "pricing", label: "Pricing", short: "Pricing", role: "Finance" },
  { key: "proposal", label: "Proposal", short: "Proposal", role: "Pre-sales" },
  { key: "handoff", label: "Delivery handoff", short: "Handoff", role: "Delivery" },
] as const;

export const MATCH_LABEL: Record<string, string> = { strong: "Strong", partial: "Partial", gap: "Gap", confirm: "Confirm" };
export const MATCH_STYLE: Record<string, string> = {
  strong: "bg-fit-strong-soft text-fit-strong-ink",
  partial: "bg-fit-partial-soft text-fit-partial-ink",
  gap: "bg-fit-gap-soft text-fit-gap-ink",
  confirm: "bg-surface text-fit-confirm-ink ring-1 ring-inset ring-fit-confirm",
};
// One definition of the match statuses for every chart: order = strongest to weakest, then unknown.
export const FIT = [
  { key: "strong", label: "Strong", long: "Covered by what you have", fill: "rgb(var(--fit-strong))", ink: "rgb(var(--fit-strong-ink))" },
  { key: "partial", label: "Partial", long: "Covered by extending it", fill: "rgb(var(--fit-partial))", ink: "rgb(var(--fit-partial-ink))" },
  { key: "gap", label: "Gap", long: "Not covered today", fill: "rgb(var(--fit-gap))", ink: "rgb(var(--fit-gap-ink))" },
  { key: "confirm", label: "To confirm", long: "Commercial or to confirm", fill: "rgb(var(--faint))", ink: "rgb(var(--fit-confirm-ink))", hollow: true },
] as const;
export const CAT_STYLE: Record<string, string> = {
  Functional: "bg-brand-50 text-brand-700",
  "Non-functional": "bg-[rgb(110_120_230/.14)] text-[rgb(var(--cat-nf))]",
  Compliance: "bg-[rgb(170_90_210/.14)] text-[rgb(var(--cat-co))]",
  Commercial: "bg-ember-50 text-ember-600",
};
export const CATEGORIES = ["Functional", "Non-functional", "Compliance", "Commercial"];


/** "1 person", "3 people", "1 engineer", "2 engineers". */
export function plural(n: number, one: string, many?: string): string {
  return `${n} ${n === 1 ? one : many || `${one}s`}`;
}
