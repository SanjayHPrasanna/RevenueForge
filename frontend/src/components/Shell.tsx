import clsx from "clsx";
import { BookOpen, Brain, Briefcase, CalendarDays, ChevronDown, FolderKanban, LayoutDashboard, LogOut, Menu, Moon, Network, PanelLeftClose, PanelLeftOpen, Radar, Settings, ShieldCheck, Sparkles, Sun, TrendingUp, Trophy, Users, X } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { prefetchRoute, warmPages } from "../lib/prefetch";
import { ErrorBoundary, PageLoader } from "./ui";
import LandingAssistant from "./LandingAssistant";

type Item = { to: string; label: string; icon: any; end?: boolean };
// grouped like the reference: a short label over each set, so the list reads at a glance
const GROUPS: { label: string; items: Item[] }[] = [
  { label: "Pipeline", items: [
    { to: "/app", label: "Home", icon: LayoutDashboard, end: true },
    { to: "/app/opportunities", label: "Opportunities", icon: Radar },
    { to: "/app/market", label: "Market insights", icon: TrendingUp },
  ] },
  { label: "Bids", items: [
    { to: "/app/deals", label: "Deals", icon: Briefcase },
    { to: "/app/calendar", label: "Calendar", icon: CalendarDays },
    { to: "/app/winloss", label: "Win/loss", icon: Trophy },
  ] },
  { label: "Delivery", items: [
    { to: "/app/projects", label: "Projects", icon: FolderKanban },
    { to: "/app/clients", label: "Customer 360", icon: Users },
  ] },
  { label: "Knowledge", items: [
    { to: "/app/library", label: "Knowledge library", icon: BookOpen },
    { to: "/app/graph", label: "Knowledge graph", icon: Network },
    { to: "/app/learning", label: "AI learning", icon: Brain },
  ] },
  { label: "Workspace", items: [{ to: "/app/settings", label: "Settings", icon: Settings }] },
];
const TITLES: [string, string][] = [["/app/opportunities", "Opportunities"], ["/app/market", "Market insights"], ["/app/projects", "Projects"], ["/app/clients", "Customer 360"],
  ["/app/deals", "Deals"], ["/app/calendar", "Calendar"], ["/app/winloss", "Win/loss"], ["/app/library", "Knowledge library"], ["/app/graph", "Knowledge graph"],
  ["/app/learning", "AI learning"], ["/app/settings", "Settings"], ["/app/platform", "Platform console"]];

function useStored(key: string, initial: string): [string, (v: string) => void] {
  const [v, setV] = useState(() => {
    try {
      return localStorage.getItem(key) || initial;
    } catch {
      return initial;
    }
  });
  const set = (x: string) => {
    setV(x);
    try {
      localStorage.setItem(key, x);
    } catch {
      /* private window: keep it for this visit only */
    }
  };
  return [v, set];
}

export function useTheme(): ["dark" | "light", () => void] {
  const [theme, setTheme] = useStored("rf-theme", "dark");
  useEffect(() => { document.documentElement.setAttribute("data-theme", theme === "light" ? "light" : "dark"); }, [theme]);
  return [theme === "light" ? "light" : "dark", () => setTheme(theme === "light" ? "dark" : "light")];
}

export function Aura() {
  return <div className="aura" aria-hidden><i /><i /><i /><i /></div>;
}

export default function Shell() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [collapsed, setCollapsed] = useStored("rf-nav-collapsed", "0");
  const mini = collapsed === "1";
  const [theme, toggleTheme] = useTheme();
  const loc = useLocation();
  const { data: company } = useQuery({ queryKey: ["company"], queryFn: () => api.get("/company") });
  const ob = company?.onboarding;
  const qc = useQueryClient();
  useEffect(() => { if (user) warmPages({ platformAdmin: !!user.platform_admin }); }, [user?.id]);
  const { data: due } = useQuery({ queryKey: ["reminders"], queryFn: () => api.get<any>("/calendar/reminders"), enabled: !!user, refetchInterval: 300000 });
  const badge: Record<string, { n: number; hot: boolean } | undefined> = { "/app/calendar": due?.count ? { n: due.count, hot: due.overdue > 0 } : undefined };
  const groups = [...GROUPS];
  if (user?.platform_admin) groups[groups.length - 1] = { ...groups[groups.length - 1], items: [...groups[groups.length - 1].items, { to: "/app/platform", label: "Platform console", icon: ShieldCheck, end: false }] };
  const title = TITLES.find(([p]) => loc.pathname.startsWith(p))?.[1] || "Home";
  const initials = (user?.name || "").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();

  const navFor = (mini: boolean) => (
    <nav className="flex flex-col h-full min-h-0">
      <div className={clsx("flex items-center gap-2.5 pb-4", mini ? "justify-center px-0" : "px-2")}>
        <img src="/brand/revenueforge-mark.png" alt="" className="h-9 w-9 rounded-[11px] shrink-0" />
        {!mini && (
          <div className="leading-tight min-w-0 flex-1">
            <div className="text-[15px] font-bold tracking-[-0.01em] text-ink">RevenueForge</div>
            <div className="text-[11.5px] text-ink-muted truncate">{company?.name || user?.tenant.name || "Your workspace"}</div>
          </div>
        )}
        {!mini && (
          <button onClick={() => setCollapsed("1")} className="hidden lg:grid h-8 w-8 place-items-center rounded-[10px] text-ink-muted hover:text-ink hover:bg-ink/[.06]" title="Collapse menu" aria-label="Collapse menu">
            <PanelLeftClose className="h-[17px] w-[17px]" />
          </button>
        )}
      </div>
      {mini && (
        <button onClick={() => setCollapsed("0")} className="mx-auto mb-2 hidden lg:grid h-8 w-8 place-items-center rounded-[10px] text-ink-muted hover:text-ink hover:bg-ink/[.06]" title="Expand menu" aria-label="Expand menu">
          <PanelLeftOpen className="h-[17px] w-[17px]" />
        </button>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto scroll-thin -mx-1 px-1">
        {groups.map((g) => (
          <div key={g.label} className="mb-3">
            {!mini && <div className="section-label px-3 pt-1.5 pb-1">{g.label}</div>}
            <div className="space-y-0.5">
              {g.items.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  onMouseEnter={() => prefetchRoute(qc, n.to)}
                  onFocus={() => prefetchRoute(qc, n.to)}
                  onClick={() => setOpen(false)}
                  title={mini ? n.label : undefined}
                  className={({ isActive }) =>
                    clsx(
                      "group relative flex items-center rounded-[14px] h-9 text-[13.5px] font-semibold transition-colors duration-200",
                      mini ? "justify-center" : "gap-3 px-3",
                      isActive ? "text-ink bg-ink/[.07] shadow-[inset_0_0_0_1px_rgb(var(--line)/.1)]" : "text-ink-muted hover:text-ink hover:bg-ink/[.04]",
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <n.icon className={clsx("h-[18px] w-[18px] shrink-0", isActive ? "text-brand-600" : "")} />
                      {!mini && <span className="truncate">{n.label}</span>}
                      {badge[n.to] && (
                        <span className={clsx("num text-[10.5px] font-bold rounded-full min-w-[20px] h-5 px-1.5 grid place-items-center", mini ? "absolute -top-0.5 -right-0.5" : "ml-auto",
                          badge[n.to]!.hot ? "bg-fit-gap text-white" : "bg-ink/[.1] text-ink-soft")} title={`${badge[n.to]!.n} deadline${badge[n.to]!.n > 1 ? "s" : ""} coming up for you`}>{badge[n.to]!.n}</span>
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </div>
      {ob && !ob.complete && (mini ? (
        <NavLink to="/onboarding" title={`Finish setting up (${ob.pct}%)`} className="mx-auto mb-2 h-9 w-9 rounded-[12px] grid place-items-center bg-brand-500/15 text-brand-600 hover:bg-brand-500/25">
          <Sparkles className="h-4 w-4" />
        </NavLink>
      ) : (
        <NavLink to="/onboarding" className="mb-2 rounded-[16px] px-3.5 py-3 text-[12.5px] bg-brand-500/[.1] shadow-[inset_0_0_0_1px_rgb(var(--b500)/.18)] hover:bg-brand-500/[.15]">
          <div className="flex items-center gap-2 font-semibold text-ink"><Sparkles className="h-4 w-4 text-brand-600" /> Finish setting up</div>
          <div className="mt-2 h-1 rounded-full bg-ink/[.1]"><div className="h-1 rounded-full bg-brand-500" style={{ width: `${ob.pct}%` }} /></div>
          <div className="mt-1.5 text-ink-muted text-[11.5px]">{ob.pct}% of your company pack uploaded</div>
        </NavLink>
      ))}
      <div className={clsx("pt-3 border-t border-line flex items-center gap-2.5", mini && "justify-center")} title={mini ? `${user?.name} · ${user?.email}` : undefined}>
        <span className="h-9 w-9 shrink-0 rounded-full grid place-items-center text-[12px] font-bold text-white bg-gradient-to-br from-brand-400 to-brand-600">{initials}</span>
        {!mini && (
          <div className="min-w-0 leading-tight">
            <div className="text-[13px] font-semibold text-ink truncate">{user?.name}</div>
            <div className="text-[11.5px] text-ink-muted truncate capitalize">{user?.role}</div>
          </div>
        )}
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen relative">
      <Aura />
      <aside className={clsx("glass hidden lg:block fixed z-30 top-3.5 bottom-3.5 left-3.5 rounded-3xl p-3 pt-4 transition-[width] duration-300 ease-apple", mini ? "w-[72px]" : "w-[252px]")}>
        {navFor(mini)}
      </aside>
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 bg-black/40 backdrop-blur-sm anim-fade-in" onClick={() => setOpen(false)}>
          <aside className="glass absolute top-3 bottom-3 left-3 w-[260px] rounded-3xl p-3 pt-4" style={{ animation: "page-in .3s cubic-bezier(.22,1,.36,1) both" }} onClick={(e) => e.stopPropagation()}>
            <button className="absolute top-4 right-3 h-8 w-8 grid place-items-center rounded-[10px] text-ink-muted hover:bg-ink/[.06]" onClick={() => setOpen(false)} aria-label="Close menu">
              <X className="h-4 w-4" />
            </button>
            {navFor(false)}
          </aside>
        </div>
      )}
      <div className={clsx("relative z-[1] min-w-0 flex flex-col min-h-screen transition-[padding] duration-300 ease-apple", mini ? "lg:pl-[86px]" : "lg:pl-[266px]")}>
        <header className="sticky top-0 z-20 px-3 lg:px-4 pt-3.5">
          <div className="glass rounded-[20px] min-h-[58px] flex items-center gap-2 pl-4 pr-2.5 py-2 max-w-[1480px] mx-auto">
            <button className="lg:hidden btn-ghost px-2 -ml-2" onClick={() => setOpen(true)} aria-label="Open menu">
              <Menu className="h-5 w-5" />
            </button>
            <div className="text-[13px] text-ink-muted truncate flex items-center gap-1.5">
              <span className="hidden sm:inline">{user?.tenant.name}</span>
              <span className="hidden sm:inline text-ink-faint">›</span>
              <span className="font-semibold text-ink">{title}</span>
            </div>
            <div className="flex-1" />
            {company?.llm && (
              <span
                className={clsx("hidden md:inline-flex chip", company.llm.enabled ? "bg-ok/[.14] text-ok" : "bg-ink/[.07] text-ink-muted")}
                title={company.llm.enabled ? `AI engine: ${company.llm.provider} ${company.llm.model}` : company.llm.disabled_reason || "AI is off. Add GEMINI_API_KEY to backend/.env and restart."}
              >
                <span className={clsx("h-1.5 w-1.5 rounded-full", company.llm.enabled ? "bg-ok" : "bg-ink-faint")} />
                {company.llm.enabled ? `AI · ${company.llm.provider}` : company.llm.disabled_reason ? "AI key problem" : "AI off · rules engine"}
              </span>
            )}
            <button onClick={toggleTheme} className="h-9 w-9 grid place-items-center rounded-[12px] text-ink-soft hover:text-ink hover:bg-ink/[.06] shadow-[inset_0_0_0_1px_rgb(var(--line)/.12)]"
              title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"} aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
              {theme === "dark" ? <Sun className="h-[17px] w-[17px]" /> : <Moon className="h-[17px] w-[17px]" />}
            </button>
            <div className="relative">
              <button className="flex items-center gap-1.5 rounded-[12px] pl-1 pr-1.5 h-9 hover:bg-ink/[.06]" onClick={() => setMenu((m) => !m)} aria-label="Account menu">
                <span className="h-7 w-7 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-white text-[11px] font-bold grid place-items-center">{initials}</span>
                <ChevronDown className="h-4 w-4 text-ink-muted" />
              </button>
              {menu && (
                <div className="absolute right-0 mt-2 glass rounded-[16px] w-60 p-1.5 text-[13px] anim-scale-in origin-top-right" onMouseLeave={() => setMenu(false)}>
                  <div className="px-3 py-2">
                    <div className="font-semibold text-ink truncate">{user?.name}</div>
                    <div className="text-[12px] text-ink-muted truncate">{user?.email}</div>
                  </div>
                  <div className="h-px bg-line my-1" />
                  <a className="w-full text-left px-3 h-9 rounded-[10px] hover:bg-ink/[.06] flex items-center gap-2.5" href="/trust" target="_blank" rel="noreferrer">
                    <ShieldCheck className="h-4 w-4 text-ink-muted" /> Trust & data
                  </a>
                  <button className="w-full text-left px-3 h-9 rounded-[10px] hover:bg-ink/[.06] flex items-center gap-2.5" onClick={logout}>
                    <LogOut className="h-4 w-4 text-ink-muted" /> Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        {/* The loading boundary sits outside the per-page <main>, so while the next page gets ready the current one
            stays on screen (navigation runs as a transition) instead of flashing a loading screen. */}
        <Suspense fallback={<PageLoader />}>
          <main key={loc.pathname.split("/").slice(0, 3).join("/")} className="flex-1 min-w-0 w-full max-w-[1480px] mx-auto page-enter pb-20 lg:pr-1">
            <ErrorBoundary resetKey={loc.pathname}><Outlet /></ErrorBoundary>
          </main>
        </Suspense>
        {<LandingAssistant mode="workspace" company={company?.name} />}
      </div>
    </div>
  );
}
