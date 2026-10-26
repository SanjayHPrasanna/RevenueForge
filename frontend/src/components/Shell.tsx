import clsx from "clsx";
import { NoticeBar } from "./GoogleButton";
import { BookOpen, Brain, Briefcase, ChevronDown, LayoutDashboard, LogOut, Menu, Network, Settings, Sparkles, X } from "lucide-react";
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
  const loc = useLocation();
  const { data: company } = useQuery({ queryKey: ["company"], queryFn: () => api.get("/company") });
  const ob = company?.onboarding;

  const nav = (
    <nav className="flex flex-col h-full">
      <div className="px-5 pt-5 pb-6">
        <ProductMark white />
      </div>
      <div className="px-3 flex-1 space-y-0.5">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            onClick={() => setOpen(false)}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-3 rounded-md px-3 h-10 text-[14px] font-medium transition-colors",
                isActive ? "bg-white/10 text-white" : "text-brand-100/80 hover:text-white hover:bg-white/5",
              )
            }
          >
            {({ isActive }) => (
              <>
                <n.icon className={clsx("h-[18px] w-[18px]", isActive ? "text-ember-400" : "")} />
                {n.label}
              </>
            )}
          </NavLink>
        ))}
      </div>
      {ob && !ob.complete && (
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
      <div className="px-5 py-4 border-t border-white/10 text-[11.5px] text-brand-200/80">
        <div className="text-white/90 font-semibold text-[12.5px] truncate">{company?.name || "Your workspace"}</div>
        <div className="truncate">{user?.email}</div>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen flex">
      <aside className="hidden lg:block w-[248px] shrink-0 bg-brand-900 fixed inset-y-0 left-0 z-30">{nav}</aside>
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 bg-brand-950/50" onClick={() => setOpen(false)}>
          <aside className="w-[260px] h-full bg-brand-900" onClick={(e) => e.stopPropagation()}>
            <button className="absolute top-4 left-[220px] text-white" onClick={() => setOpen(false)} aria-label="Close menu">
              <X className="h-5 w-5" />
            </button>
            {nav}
          </aside>
        </div>
      )}
      <div className="flex-1 lg:ml-[248px] min-w-0 flex flex-col">
        <NoticeBar text={company ? company.notice || "" : undefined} />
        <header className="h-14 bg-white border-b border-line flex items-center gap-3 px-4 lg:px-6 sticky top-0 z-20">
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
              <span className="h-7 w-7 rounded-full bg-brand-800 text-white text-[12px] font-bold grid place-items-center">
                {user?.name.split(" ").map((p) => p[0]).slice(0, 2).join("")}
              </span>
              <span className="hidden sm:block text-left leading-tight">
                <span className="block text-[13px] font-semibold">{user?.name}</span>
                <span className="block text-[11.5px] text-ink-muted capitalize">{user?.role}</span>
              </span>
              <ChevronDown className="h-4 w-4 text-ink-muted" />
            </button>
            {menu && (
              <div className="absolute right-0 mt-1 card shadow-lift w-56 py-1 text-sm" onMouseLeave={() => setMenu(false)}>
                <div className="px-3 py-2 text-[12px] text-ink-muted border-b border-line-soft">{user?.email}</div>
                <button className="w-full text-left px-3 py-2 hover:bg-paper flex items-center gap-2" onClick={logout}>
                  <LogOut className="h-4 w-4" /> Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <main key={loc.pathname.split("/").slice(0, 3).join("/")} className="flex-1 min-w-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
