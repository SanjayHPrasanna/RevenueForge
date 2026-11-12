import type { QueryClient } from "@tanstack/react-query";
import { api } from "./api";

/** Every workspace page's code, loaded on demand. Calling one twice costs nothing: the browser keeps the module. */
export const PAGES = {
  dashboard: () => import("../pages/Dashboard"),
  deal: () => import("../pages/DealWorkspace"),
  deals: () => import("../pages/Deals"),
  graph: () => import("../pages/Graph"),
  learning: () => import("../pages/Learning"),
  library: () => import("../pages/Library"),
  onboarding: () => import("../pages/Onboarding"),
  settings: () => import("../pages/Settings"),
  winloss: () => import("../pages/WinLoss"),
  radar: () => import("../pages/Radar"),
  market: () => import("../pages/Market"),
  customers: () => import("../pages/Customers"),
  platform: () => import("../pages/Platform"),
  calendar: () => import("../pages/Calendar"),
  trust: () => import("../pages/Trust"),
  buyer: () => import("../pages/Buyer"),
};

/** Which page code and which data a sidebar link needs, so hovering it can fetch both before the click. */
const ROUTES: Record<string, { page: keyof typeof PAGES; data?: [unknown[], string] }> = {
  "/app": { page: "dashboard", data: [["dashboard"], "/dashboard"] },
  "/app/deals": { page: "deals", data: [["deals"], "/deals"] },
  "/app/calendar": { page: "calendar" },
  "/app/library": { page: "library", data: [["lib", "capabilities"], "/library/capabilities"] },
  "/app/graph": { page: "graph" },
  "/app/opportunities": { page: "radar" },
  "/app/market": { page: "market" },
  "/app/customers": { page: "customers" },
  "/app/winloss": { page: "winloss" },
  "/app/learning": { page: "learning" },
  "/app/settings": { page: "settings" },
  "/app/platform": { page: "platform" },
  "/app/buyer": { page: "buyer" },
};

const idle = (fn: () => void) => ((window as any).requestIdleCallback ? (window as any).requestIdleCallback(fn, { timeout: 4000 }) : setTimeout(fn, 1500));

/** Once the workspace has drawn, quietly download the other pages' code, so the first visit to each has no loading spinner. */
export function warmPages(opts: { buyer: boolean; platformAdmin: boolean }) {
  const keys = (opts.buyer ? ["buyer", "settings", "trust"] : Object.keys(PAGES).filter((k) => k !== "buyer")) as (keyof typeof PAGES)[];
  const list = keys.filter((k) => k !== "platform" || opts.platformAdmin);
  idle(() => {
    let i = 0;
    const next = () => { if (i < list.length) PAGES[list[i++]]().catch(() => undefined).finally(() => idle(next)); };
    next();
  });
}

/** Hovering a sidebar link: fetch its page code and its first data, so the page opens with content. */
export function prefetchRoute(qc: QueryClient, to: string) {
  const r = ROUTES[to];
  if (!r) return;
  PAGES[r.page]().catch(() => undefined);
  if (r.data) qc.prefetchQuery({ queryKey: r.data[0], queryFn: () => api.get(r.data![1]), staleTime: 15_000 });
  if (to === "/app/calendar") {
    const c = calendarQuery(new Date(), readPref("rf-cal-view", "month"), readPref("rf-cal-tenders", "saved_strong"));
    qc.prefetchQuery({ queryKey: c.key, queryFn: () => api.get(c.url), staleTime: 15_000 });
  }
}

const readPref = (k: string, d: string) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The calendar's data request for a month: the six-week grid in month view, three months in list view. Shared with the page. */
export function calendarQuery(month: Date, view: string, tenders: string) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const gridStart = new Date(first); gridStart.setDate(1 - ((first.getDay() + 6) % 7));
  const gridEnd = new Date(gridStart); gridEnd.setDate(gridStart.getDate() + 41);
  const [a, b] = view === "month" ? [isoDay(gridStart), isoDay(gridEnd)] : [isoDay(first), isoDay(new Date(month.getFullYear(), month.getMonth() + 3, 0))];
  return { key: ["calendar", a, b, tenders], url: `/calendar?start=${a}&end=${b}&tenders=${tenders}` };
}

/** Hovering a deal: fetch the deal so its page opens straight away. */
export function prefetchDeal(qc: QueryClient, id: string) {
  PAGES.deal().catch(() => undefined);
  qc.prefetchQuery({ queryKey: ["deal", id], queryFn: () => api.get(`/deals/${id}`), staleTime: 15_000 });
  // The deal's header figures (effort, coverage) come from these two.
  qc.prefetchQuery({ queryKey: ["stage", id, "estimation"], queryFn: () => api.get(`/deals/${id}/stages/estimation`), staleTime: 30_000 });
  qc.prefetchQuery({ queryKey: ["reqs", id], queryFn: () => api.get(`/deals/${id}/requirements`), staleTime: 30_000 });
}

const STAGE_KEYS = ["matching", "architecture", "estimation", "pricing", "proposal", "handoff"];

/** With a deal open, fetch the other stages in the background, so moving between stages is instant. */
export function prefetchStages(qc: QueryClient, id: string) {
  idle(() => {
    qc.prefetchQuery({ queryKey: ["reqs", id], queryFn: () => api.get(`/deals/${id}/requirements`), staleTime: 30_000 });
    STAGE_KEYS.forEach((s) => qc.prefetchQuery({ queryKey: ["stage", id, s], queryFn: () => api.get(`/deals/${id}/stages/${s}`), staleTime: 30_000 }));
    // Review notes for every stage arrive in one call; split them so each stage's notes box opens filled.
    qc.fetchQuery({ queryKey: ["notes", id, "all"], queryFn: () => api.get<any[]>(`/deals/${id}/notes`), staleTime: 30_000 }).then((all) => {
      ["requirements", ...STAGE_KEYS, "gaps"].forEach((s) => {
        if (!qc.getQueryData(["notes", id, s])) qc.setQueryData(["notes", id, s], all.filter((n: any) => n.stage === s));
      });
    }).catch(() => undefined);
  });
}
