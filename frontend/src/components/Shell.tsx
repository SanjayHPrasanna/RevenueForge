import clsx from "clsx";
import { NoticeBar } from "./GoogleButton";
import { BookOpen, Brain, Briefcase, ChevronDown, ChevronLeft, ChevronRight, LayoutDashboard, LogOut, Menu, Network, Settings, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ProductMark } from "./ui";

const NAV = [
  { to: "/app", label: "Home", icon: LayoutDashboard, end: true },
  { to: "/app/deals", label: "Deals", icon: Briefcase },
  { to: "/app/library", label: "Knowledge library", icon: BookOpen },
  { to: "/app/graph", label: "Knowledge graph", icon: Network },
  { to: "/app/learning", label: "AI learning", icon: Brain },
  { to: "/app/settings", label: "Settings", icon: Settings },
];

export default function Shell() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [mini, setMini] = useState(() => {
    try {
      return localStorage.getItem("rf-nav-collapsed") === "1";
    } catch {
      return false;
    }
  });
  const toggleMini = () =>
    setMini((m) => {
      try {
        localStorage.setItem("rf-nav-collapsed", m ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !m;
    });
  const loc = useLocation();
  const { data: company } = useQuery({ queryKey: ["company"], queryFn: () => api.get("/company") });
  const ob = company?.onboarding;

  const navFor = (mini: boolean) => (
    <nav className="relative flex flex-col h-full overflow-hidden">
      <span aria-hidden className="pointer-events-none absolute -top-24 -left-16 h-64 w-64 rounded-full bg-brand-500/20 blur-3xl" />
      <span aria-hidden className="pointer-events-none absolute inset-y-0 right-0 w-px bg-gradient-to-b from-white/10 via-white/5 to-transparent" />
      <div className={clsx("pt-5 pb-6", mini ? "px-0 flex justify-center" : "px-5")}>
        {mini ? <img src="/brand/revenueforge-mark.svg" alt="RevenueForge" className="h-8 w-8" /> : <ProductMark white />}
      </div>
      <div className={clsx("flex-1 space-y-0.5", mini ? "px-2" : "px-3")}>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            onClick={() => setOpen(false)}
            title={mini ? n.label : undefined}
            className={({ isActive }) =>
              clsx(
                "group relative flex items-center rounded-[10px] h-10 text-[14px] font-medium transition-all duration-200 ease-apple",
                mini ? "justify-center" : "gap-3 px-3",
                isActive
                  ? "bg-gradient-to-r from-white/[.13] to-white/[.04] text-white shadow-[inset_0_1px_0_rgba(255,255,255,.08),0_6px_16px_-10px_rgba(0,0,0,.6)]"
                  : "text-brand-100/75 hover:text-white hover:bg-white/[.06]",
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive && <span aria-hidden className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-ember-400 shadow-[0_0_12px_rgba(247,154,94,.7)]" />}
                <n.icon className={clsx("h-[18px] w-[18px] shrink-0 transition-transform duration-200 ease-apple group-hover:scale-110", isActive ? "text-ember-400" : "")} />
                {!mini && n.label}
              </>
            )}
          </NavLink>
        ))}
      </div>
      {ob && !ob.complete && mini && (
        <NavLink to="/onboarding" title={`Finish setting up (${ob.pct}%)`} className="mx-2 mb-3 h-10 rounded-md bg-white/10 grid place-items-center hover:bg-white/15">
          <Sparkles className="h-4 w-4 text-ember-400" />
        </NavLink>
      )}
      {ob && !ob.complete && !mini && (
        <NavLink to="/onboarding" className="mx-3 mb-3 rounded-md bg-white/10 px-3 py-3 text-[13px] text-brand-50 hover:bg-white/10">
          <div className="flex items-center gap-2 font-semibold">
            <Sparkles className="h-4 w-4 text-ember-400" /> Finish setting up
          </div>
          <div className="mt-2 h-1 rounded bg-white/15">
            <div className="h-1 rounded bg-ember-400" style={{ width: `${ob.pct}%` }} />
          </div>
          <div className="mt-1.5 text-brand-200 text-[12px]">{ob.pct}% of your company pack uploaded</div>
        </NavLink>
      )}
      {mini ? (
        <div className="py-4 border-t border-white/10 grid place-items-center" title={`${company?.name || "Your workspace"} · ${user?.email || ""}`}>
          <span className="h-8 w-8 rounded-full bg-white/10 text-white text-[11px] font-bold grid place-items-center">
            {(company?.name || "W").slice(0, 2).toUpperCase()}
          </span>
        </div>
      ) : (
        <div className="px-5 py-4 border-t border-white/10 text-[11.5px] text-brand-200/80">
          <div className="text-white/90 font-semibold text-[12.5px] truncate">{company?.name || "Your workspace"}</div>
          <div className="truncate">{user?.email}</div>
        </div>
      )}
    </nav>
  );

  return (
    <div className="min-h-screen flex">
      <aside
        className={clsx(
          "hidden lg:block shrink-0 fixed inset-y-0 left-0 z-30 transition-[width] duration-300 ease-apple bg-gradient-to-b from-brand-900 via-brand-950 to-midnight-950",
          mini ? "w-[68px]" : "w-[248px]",
        )}
      >
        {navFor(mini)}
        <button
          onClick={toggleMini}
          title={mini ? "Expand menu" : "Collapse menu"}
          aria-label={mini ? "Expand menu" : "Collapse menu"}
          className="absolute top-7 -right-3 h-6 w-6 rounded-full bg-white border border-line shadow-hover grid place-items-center text-brand-800 transition-transform duration-200 ease-apple hover:scale-110 hover:text-brand-900"
        >
          {mini ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
        </button>
      </aside>
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 bg-midnight-950/50 backdrop-blur-sm anim-fade-in" onClick={() => setOpen(false)}>
          <aside className="w-[260px] h-full bg-gradient-to-b from-brand-900 via-brand-950 to-midnight-950 shadow-float" style={{ animation: "page-in .3s cubic-bezier(.22,.61,.36,1) both" }} onClick={(e) => e.stopPropagation()}>
            <button className="absolute top-4 left-[220px] text-white" onClick={() => setOpen(false)} aria-label="Close menu">
              <X className="h-5 w-5" />
            </button>
            {navFor(false)}
          </aside>
        </div>
      )}
      <div className={clsx("flex-1 min-w-0 flex flex-col ambient transition-[margin] duration-300 ease-apple", mini ? "lg:ml-[68px]" : "lg:ml-[248px]")}>
        <NoticeBar text={company ? company.notice || "" : undefined} />
        <header className="h-14 bg-white/75 backdrop-blur-xl backdrop-saturate-150 border-b border-line/70 flex items-center gap-3 px-4 lg:px-6 sticky top-0 z-20">
          <button className="lg:hidden btn-ghost px-2" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <div className="text-[13.5px] text-ink-muted truncate">
            <span className="font-semibold text-ink">{user?.tenant.name}</span>
            <span className="hidden sm:inline"> workspace</span>
          </div>
          <div className="flex-1" />
          {company?.llm && (
            <span
              className={clsx("hidden md:inline-flex chip", company.llm.enabled ? "bg-ok-bg text-ok" : "bg-line-soft text-ink-muted")}
              title={company.llm.enabled ? `AI engine: ${company.llm.provider} ${company.llm.model}${company.llm.paid ? "" : " (free tier)"}` : company.llm.disabled_reason || "AI is off. Add GEMINI_API_KEY to backend/.env and restart."}
            >
              {company.llm.enabled ? `AI: ${company.llm.provider}${company.llm.paid ? "" : " · free tier"}` : company.llm.disabled_reason ? "AI key problem" : "AI off · rules engine"}
            </span>
          )}
          <div className="relative">
            <button className="flex items-center gap-2 rounded-md px-2 h-9 hover:bg-line-soft" onClick={() => setMenu((m) => !m)}>
              <span className="h-7 w-7 rounded-full bg-gradient-to-br from-brand-500 to-brand-900 text-white text-[12px] font-bold grid place-items-center shadow-[0_2px_6px_-2px_rgba(8,43,61,.5)] ring-2 ring-white">
                {user?.name.split(" ").map((p) => p[0]).slice(0, 2).join("")}
              </span>
              <span className="hidden sm:block text-left leading-tight">
                <span className="block text-[13px] font-semibold">{user?.name}</span>
                <span className="block text-[11.5px] text-ink-muted capitalize">{user?.role}</span>
              </span>
              <ChevronDown className="h-4 w-4 text-ink-muted" />
            </button>
            {menu && (
              <div className="absolute right-0 mt-1.5 card shadow-lift w-56 py-1 text-sm anim-scale-in origin-top-right" onMouseLeave={() => setMenu(false)}>
                <div className="px-3 py-2 text-[12px] text-ink-muted border-b border-line-soft">{user?.email}</div>
                <button className="w-full text-left px-3 py-2 hover:bg-paper flex items-center gap-2" onClick={logout}>
                  <LogOut className="h-4 w-4" /> Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <main key={loc.pathname.split("/").slice(0, 3).join("/")} className="flex-1 min-w-0 page-enter">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
