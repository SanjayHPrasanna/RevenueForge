import clsx from "clsx";
import { ArrowRight, Check, EyeOff, FileSearch, Lock, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ProductMark } from "../components/ui";
import { Reveal, useScrollProgress, useTilt } from "../components/motion";
import LandingAssistant from "../components/LandingAssistant";
import { CoverageMap, FitLegend, PriceLadder, ReadinessScale } from "../components/viz";
import { useAuth } from "../lib/auth";
import { STAGES } from "../lib/format";

const NAV: [string, string][] = [["#how", "How it works"], ["#learning", "Self-learning AI"], ["#security", "Security"], ["#compare", "Why RevenueForge"]];

// Shared page rhythm: one container width, one section padding, one heading style.
const WRAP = "mx-auto max-w-6xl px-5 md:px-8";
const SECTION = "py-20 md:py-28";

function SectionHeading({ title, intro, dark = false, eyebrow }: { title: string; intro?: ReactNode; dark?: boolean; eyebrow?: string }) {
  return (
    <Reveal className="max-w-2xl">
      {eyebrow && <div className={clsx("eyebrow mb-4", dark && "text-brand-200")}>{eyebrow}</div>}
      <h2 className={clsx("font-display font-medium text-[34px] md:text-[48px] leading-[1.05] tracking-[-0.025em] text-balance", dark ? "text-white" : "text-brand-950")}>{title}</h2>
      {intro && <p className={clsx("mt-5 text-[16.5px] md:text-[18px] leading-[1.6]", dark ? "text-brand-100/75" : "text-ink-soft")}>{intro}</p>}
    </Reveal>
  );
}

// ---------------------------------------------------------------- header
function Header() {
  const { user } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <header className="fixed inset-x-0 top-0 z-40 px-3 md:px-5 pt-3">
      <div className={clsx("mx-auto max-w-6xl h-14 flex items-center gap-4 lg:gap-10 rounded-2xl pl-3 pr-2 md:pl-5 transition-all duration-500 ease-apple",
        "bg-white/80 backdrop-blur-xl backdrop-saturate-150 border border-white/70",
        scrolled ? "shadow-lift" : "shadow-[0_10px_40px_-20px_rgba(3,15,23,.6)]")}>
        <Link to="/" aria-label="RevenueForge home" className="shrink-0">
          <span className="hidden sm:block"><ProductMark /></span>
          <img src="/brand/revenueforge-mark.svg" alt="" className="h-8 w-8 sm:hidden" />
        </Link>
        <nav aria-label="Main" className="hidden lg:flex items-center gap-1 text-[14px] font-medium text-ink-soft">
          {NAV.map(([href, label]) => <a key={href} href={href} className="rounded-lg px-3 py-1.5 hover:bg-ink/[.05] hover:text-brand-950 transition-colors">{label}</a>)}
        </nav>
        <div className="ml-auto flex items-center gap-1.5">
          {user ? (
            <Link to="/app" className="btn-dark h-10 px-4">Open workspace</Link>
          ) : (
            <>
              <Link to="/login" className="btn-ghost h-10 px-3 sm:px-4 text-[14.5px] text-brand-950">Sign in</Link>
              <Link to="/signup" className="btn-dark h-10 px-3 sm:px-4">Create workspace</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------- hero
// The hero shows the product's core move: lines of an RFP become classified, traceable requirements.
const RFP_LINES = [
  { t: "4.2 Scope and Technical Requirements", h: true },
  { t: "The bidder shall expose core services through secured REST APIs with OAuth 2.0.", cat: "Functional", page: 6 },
  { t: "The solution must integrate with the existing CRM and ERP platforms in real time.", cat: "Functional", page: 7 },
  { t: "Availability of 99.9% with disaster recovery in a second region.", cat: "Non-functional", page: 9 },
  { t: "The bidder shall hold a current ISO/IEC 27001 certification.", cat: "Compliance", page: 14 },
  { t: "Payment will be made against accepted milestones, net 45 days.", cat: "Commercial", page: 18 },
];
const CAT_COLOR: Record<string, string> = {
  Functional: "bg-brand-50 text-brand-700 border-brand-200",
  "Non-functional": "bg-[#EEF0FB] text-[#4A54A8] border-[#D5D9F4]",
  Compliance: "bg-[#F3ECF8] text-[#7A3E9A] border-[#E3D2EE]",
  Commercial: "bg-ember-50 text-ember-600 border-ember-100",
};
const MATCH: { s: string; t: string }[] = [
  { s: "strong", t: "Strong match: API Management" }, { s: "strong", t: "Strong match: 12 engineers" },
  { s: "partial", t: "Partial: Cloud Operations" }, { s: "gap", t: "Gap: ISO 27001, certify or partner" }, { s: "confirm", t: "Confirm with finance" },
];
const DOT: Record<string, string> = { strong: "bg-fit-strong", partial: "bg-fit-partial", gap: "bg-fit-gap", confirm: "border-2 border-fit-confirm bg-white" };

function HeroVisual() {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setN(RFP_LINES.length);
      return;
    }
    const id = setInterval(() => setN((x) => (x >= RFP_LINES.length ? x : x + 1)), 650);
    return () => clearInterval(id);
  }, []);
  const found = Math.min(n, RFP_LINES.length - 1);
  return (
    <div className="rounded-[20px] bg-white overflow-hidden text-left ring-1 ring-black/5">
      <div className="flex items-center gap-3 px-5 md:px-6 h-12 border-b border-line-soft bg-gradient-to-b from-[#FBFCFD] to-[#F4F7F9] text-[12.5px] text-ink-muted">
        <span className="flex gap-1.5" aria-hidden><i className="h-2.5 w-2.5 rounded-full bg-[#FF6159]/80" /><i className="h-2.5 w-2.5 rounded-full bg-[#FFBD2E]/80" /><i className="h-2.5 w-2.5 rounded-full bg-[#28C941]/80" /></span>
        <span className="truncate font-medium text-ink-soft">Sample RFP, Digital Platform Programme</span>
        <span className="num ml-auto shrink-0">Page 6 of 30</span>
      </div>
      <div className="grid md:grid-cols-[1.15fr_1fr]">
        <div className="p-5 md:p-7 flex flex-col">
          <div className="doc-text text-[14.5px] leading-relaxed space-y-2">
            {RFP_LINES.map((l, i) =>
              l.h ? (
                <div key={i} className="font-sans font-semibold text-[13.5px] text-ink pb-1">{l.t}</div>
              ) : (
                <p key={i} className={clsx("rounded px-1.5 py-0.5 -mx-1.5 transition-colors duration-500", i <= n && "bg-[#FFF1D6]")}>{l.t}</p>
              ),
            )}
          </div>
          <div className="mt-auto pt-5 flex items-center gap-2 text-[12.5px] text-ink-muted" aria-live="polite">
            <span className="h-2 w-2 rounded-full bg-ok" />
            {found} of {RFP_LINES.length - 1} requirements found on this page
          </div>
        </div>
        <div className="border-t md:border-t-0 md:border-l border-line bg-[#FBFCFD] p-5 md:p-6">
          <div className="text-[12.5px] font-semibold text-ink-muted mb-3">Extracted and matched</div>
          <ul className="divide-y divide-line-soft">
            {RFP_LINES.slice(1).map((l, i) => (
              <li key={i} className={clsx("py-3 transition-all duration-500", i + 1 <= n ? "opacity-100 translate-y-0" : "opacity-0 translate-y-1")}>
                <div className="flex items-center gap-2 text-[11.5px]">
                  <span className="num font-semibold text-ink-muted">REQ-{String(i + 41).padStart(3, "0")}</span>
                  <span className={clsx("chip border", CAT_COLOR[l.cat!])}>{l.cat}</span>
                  <span className="ml-auto text-ink-faint num">p. {l.page}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-2 text-[13px] text-ink-soft">
                  <span className={clsx("h-2 w-2 rounded-full shrink-0", DOT[MATCH[i].s])} aria-hidden />
                  <span className="truncate">{MATCH[i].t}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

/** A pre-sales photo on the right of the headline (large screens only). It sits beside the words, never behind them,
 * and stays hidden until it loads so the page never shows a broken image. */
const PHOTO_MASK = "linear-gradient(90deg, transparent 0%, #000 55%), linear-gradient(180deg, transparent 0%, #000 22%, #000 55%, transparent 100%)";
function HeroPhoto() {
  const [ok, setOk] = useState(false);
  return (
    <div aria-hidden className={clsx("pointer-events-none absolute inset-y-0 right-0 w-[52%] hidden lg:block transition-opacity duration-1000", ok ? "opacity-100" : "opacity-0")}>
      <img src="/hero/presales.jpg" alt="" onLoad={() => setOk(true)} onError={() => setOk(false)}
        className="absolute inset-0 h-full w-full object-cover object-[center_30%] opacity-[.42] saturate-[.75] mix-blend-luminosity"
        style={{ WebkitMaskImage: PHOTO_MASK, maskImage: PHOTO_MASK, WebkitMaskComposite: "source-in", maskComposite: "intersect" }} />
    </div>
  );
}

const PROOF = [
  "Every requirement traced to its page in the RFP",
  "Eight stages, each approved by the right person",
  "Client names masked in screens, AI prompts and documents",
];

/** Floating glass cards around the product shot (large screens only), each on its own depth plane. */
function FloatCard({ className, z, children, slow }: { className: string; z: number; children: ReactNode; slow?: boolean }) {
  return (
    <div aria-hidden className={clsx("absolute hidden lg:block", className)} style={{ transform: `translateZ(${z}px)` }}>
      <div className={clsx("rounded-2xl bg-white/90 backdrop-blur-xl border border-white/80 shadow-float px-4 py-3 text-left", slow ? "float-slower" : "float-slow")}>
        {children}
      </div>
    </div>
  );
}

/** The product shot: starts tilted back like a camera looking down at it, and settles flat as you scroll. */
function HeroStage() {
  const [ref, p] = useScrollProgress<HTMLDivElement>(0.35);
  const tilt = useTilt<HTMLDivElement>(3);
  const rx = 24 * (1 - p);
  return (
    <div ref={ref} className="relative perspective" style={{ perspectiveOrigin: "50% 0%" }}>
      <div className="relative preserve-3d will-change-transform"
        style={{ transform: `rotateX(${rx.toFixed(2)}deg) scale(${(0.9 + 0.1 * p).toFixed(3)}) translateY(${(-20 * (1 - p)).toFixed(1)}px)`, transformOrigin: "50% 0%" }}>
        <div ref={tilt} className="tilt tilt-glare rounded-[20px] shadow-float">
          <HeroVisual />
        </div>
        <FloatCard className="-left-28 bottom-20" z={80}>
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">Bid readiness</div>
          <div className="mt-1 flex items-baseline gap-2"><span className="font-display num text-[30px] leading-none text-brand-950">84%</span><span className="text-[12px] font-semibold text-ok">+48 with plan</span></div>
          <div className="mt-2 h-1.5 w-40 rounded-full bg-line-soft overflow-hidden"><div className="h-full w-[84%] rounded-full bg-gradient-to-r from-brand-400 to-ok" /></div>
        </FloatCard>
        <FloatCard className="-right-24 -top-14" z={120} slow>
          <div className="flex items-center gap-2 text-[12.5px] font-semibold text-ink"><span className="h-2 w-2 rounded-full bg-fit-strong" /> Strong match</div>
          <div className="mt-0.5 text-[12px] text-ink-muted">API Management · 3 case studies</div>
        </FloatCard>
        <FloatCard className="-right-20 -bottom-9" z={60}>
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">Target price</div>
          <div className="mt-1 font-display num text-[24px] leading-none text-brand-950">AUD 3.21M</div>
          <div className="mt-1 text-[12px] text-ink-muted">28% margin · 17 people</div>
        </FloatCard>
      </div>
    </div>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="relative stage-dark text-white">
        <div aria-hidden className="absolute inset-0 grid-lines" />
        <div aria-hidden className="absolute -top-40 left-1/2 -ml-[420px] h-[640px] w-[840px] rounded-full bg-brand-500/25 blur-[120px] drift" />
        <HeroPhoto />
        <div className={clsx(WRAP, "relative pt-36 pb-24 md:pt-44 md:pb-32")}>
          <div className="max-w-[40rem] stagger">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[.06] px-3 py-1 text-[12.5px] font-medium text-brand-100 backdrop-blur">
              <Sparkles className="h-3.5 w-3.5 text-ember-400" aria-hidden /> Deal and proposal intelligence for pre-sales teams
            </div>
            <h1 className="mt-6 font-display font-medium text-[44px] sm:text-[58px] lg:text-[72px] leading-[1.0] tracking-[-0.035em] text-balance">
              Turn an RFP into a proposal you can sign&nbsp;off, <span className="text-gradient">in&nbsp;hours.</span>
            </h1>
            <p className="mt-7 text-[17px] md:text-[19px] leading-[1.6] text-brand-100/80 max-w-[34rem]">
              RevenueForge reads the whole document, matches every requirement to what your company has actually delivered, and drafts the
              architecture, team, price, proposal and delivery handoff. Your experts review and approve each step.
            </p>
            <div className="mt-9 flex flex-col sm:flex-row gap-3">
              <Link to="/signup" className="btn btn-lg bg-white text-brand-950 shadow-[0_10px_30px_-10px_rgba(159,209,235,.6)] hover:bg-brand-50 group">
                Create your company workspace <ArrowRight className="h-4 w-4 transition-transform duration-300 ease-apple group-hover:translate-x-0.5" />
              </Link>
              <a href="#how" className="btn btn-lg border border-white/20 bg-white/[.06] text-white backdrop-blur hover:bg-white/[.12]">See how it works</a>
            </div>
            <ul className="mt-11 flex flex-col gap-2.5 text-[14.5px] text-brand-100/80">
              {PROOF.map((p) => (
                <li key={p} className="flex items-start gap-2.5">
                  <span className="mt-[2px] h-[18px] w-[18px] shrink-0 rounded-full bg-white/10 border border-white/15 grid place-items-center">
                    <Check className="h-3 w-3 text-brand-200" strokeWidth={3} aria-hidden />
                  </span>
                  {p}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
      {/* the product shot rises out of the midnight stage into the light page below */}
      <div className="relative">
        <div aria-hidden className="absolute inset-x-0 top-0 h-[55%] bg-gradient-to-b from-[#0A2433] to-[#0A2433]" />
        <div aria-hidden className="absolute inset-x-0 top-[55%] bottom-0 bg-gradient-to-b from-white to-paper" />
        <div className={clsx(WRAP, "relative max-w-5xl -mt-10 md:-mt-16")}>
          <HeroStage />
        </div>
      </div>
      <div className="bg-paper h-20 md:h-28" />
    </section>
  );
}

// ---------------------------------------------------------------- the whole bid
// A fixed, invented sample bid for the "whole bid on one screen" section.
const SAMPLE_SECTIONS: [string, string][] = [
  ["3.1 Integration and APIs", "SSPPGSCSPG"], ["3.2 Real-time events", "GPPSCG"], ["3.3 Data and analytics", "PSPC"],
  ["4. Non-functional", "SSPGSPSPGS"], ["5. Security and compliance", "SCSSGPSS"], ["6. Managed services", "PPSSPSPSS"],
  ["7. Project delivery", "CPSC"], ["8. Deliverables", "SPPGSP"], ["9. Commercial terms", "CCCCC"],
];
const SAMPLE_REQS = SAMPLE_SECTIONS.flatMap(([sec, code], si) => code.split("").map((c, i) => ({
  id: `${si}-${i}`, section: sec, block_idx: si * 20 + i, code: `REQ-${String(si * 12 + i + 1).padStart(3, "0")}`, page: 4 + si * 3,
  priority: (si + i) % 5 === 4 ? "Desirable" : "Mandatory", category: sec.startsWith("9") ? "Commercial" : sec.startsWith("4") ? "Non-functional" : sec.startsWith("5") ? "Compliance" : "Functional",
  match_status: { S: "strong", P: "partial", G: "gap", C: "confirm" }[c], text: `Sample requirement from section ${sec}.`,
})));

const PANEL = "rounded-2xl bg-white p-6 ring-1 ring-white/10 shadow-[0_40px_80px_-40px_rgba(0,0,0,.7)] tilt tilt-glare";
const PANEL_TITLE = "text-[14px] font-semibold text-ink";

function TiltPanel({ className, children }: { className: string; children: ReactNode }) {
  const ref = useTilt<HTMLDivElement>(2.5);
  return <div ref={ref} className={className}>{children}</div>;
}

function WholeBid() {
  const counts: Record<string, number> = {};
  SAMPLE_REQS.forEach((r) => (counts[r.match_status!] = (counts[r.match_status!] || 0) + 1));
  const fmt = (v: number) => `AUD ${(v / 1e6).toFixed(2)}M`;
  return (
    <section className="relative overflow-hidden stage-dark text-white">
      <div aria-hidden className="absolute inset-0 grid-lines opacity-70" />
      <div className={clsx(WRAP, SECTION, "relative")}>
        <SectionHeading dark eyebrow="Decide faster" title="The whole bid on one screen."
          intro="Every requirement becomes one tile, coloured by whether you can deliver it today. Next to it: whether to bid, and what the price does to your margin. Decide in minutes, not after a week of spreadsheets." />
        <Reveal className="mt-14 grid lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] gap-5 text-ink">
          <TiltPanel className={PANEL}>
            <div className={PANEL_TITLE}>Coverage map</div>
            <FitLegend counts={counts} className="mt-2 mb-5" />
            <CoverageMap reqs={SAMPLE_REQS} />
          </TiltPanel>
          <div className="grid gap-5">
            <TiltPanel className={PANEL}>
              <div className={PANEL_TITLE}>Bid decision</div>
              <div className="font-display text-[26px] leading-tight text-brand-950 mt-1 mb-5">Bid with mitigations</div>
              <ReadinessScale today={52} mitigated={81} />
            </TiltPanel>
            <TiltPanel className={PANEL}>
              <div className={clsx(PANEL_TITLE, "mb-3")}>Price against cost</div>
              <PriceLadder cost={2_310_000} floorMargin={18} selected="Target" list={4_160_000} fmt={fmt}
                scenarios={[{ name: "Aggressive", price: 2_890_000, margin_pct: 20 }, { name: "Target", price: 3_210_000, margin_pct: 28 }, { name: "Premium", price: 3_610_000, margin_pct: 36 }]} />
            </TiltPanel>
          </div>
        </Reveal>
        <p className="mt-6 text-[12.5px] text-brand-100/50">Sample data for illustration.</p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- how it works
const STAGE_COPY: Record<string, string> = {
  requirements: "Reads the RFP, RFI, RFQ or SOW and lists every requirement, classified and linked to its page.",
  matching: "Scores each requirement against your capabilities, people, case studies and certifications.",
  gaps: "Flags what you can't cover yet, with partner, hire, upskill or certify options and a bid verdict.",
  architecture: "Drafts the solution layers and technology choices, each traced to the requirements behind it.",
  estimation: "Sizes workstreams and builds a role-wise team from your skills matrix, with named people.",
  pricing: "Applies your rate card and cost, then shows aggressive, target and premium margin scenarios.",
  proposal: "Writes the proposal and compliance matrix inside your own Word template.",
  handoff: "Hands delivery the scope, assumptions, risks, team, plan and open items.",
};

function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-24 bg-paper">
      <div className={clsx(WRAP, SECTION)}>
        <SectionHeading eyebrow="How it works" title="One pipeline, eight reviewable steps"
          intro="Each step produces a draft the right person approves: pre-sales, solution architect, finance or delivery. Change anything and everything downstream updates." />
        <ol className="mt-14 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {STAGES.map((s, i) => (
            <Reveal as="li" key={s.key} delay={(i % 4) * 80} className="group card card-hover p-6 flex flex-col">
              <div className="flex items-center gap-3">
                <span className="h-8 w-8 rounded-[10px] bg-gradient-to-b from-brand-800 to-brand-950 text-white num text-[13px] font-semibold grid place-items-center shadow-btn">{i + 1}</span>
                <span className="text-[16px] font-semibold text-ink tracking-[-0.01em]">{s.label}</span>
              </div>
              <p className="mt-4 text-[14.5px] text-ink-soft leading-relaxed">{STAGE_COPY[s.key]}</p>
              <p className="mt-auto pt-4 text-[12.5px] font-medium text-brand-700">Approved by {s.role.toLowerCase()}</p>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- learning
const CHAIN = ["Requirement", "Capability", "Technology", "Skill", "Case study", "Accelerator", "Architecture", "Resource", "Cost"];
const SIGNALS: [string, string][] = [
  ["Corrections become guidance", "When a reviewer changes a category, match or answer, the most relevant past corrections shape every future draft."],
  ["Your own classifier", "Approved requirements train a model on your company's labels, which overrides generic AI where it is confident."],
  ["An answer library", "Approved answers are reused on similar requirements in later RFPs. Answers from won deals rank higher."],
  ["Outcomes calibrate estimates", "Wins, losses and actual effort tune future estimates and show win rate by margin band."],
];

function Learning() {
  return (
    <section id="learning" className="scroll-mt-24 bg-white border-y border-line/70">
      <div className={clsx(WRAP, SECTION, "grid lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] gap-14 lg:gap-20 items-start")}>
        <div>
          <SectionHeading eyebrow="Self-learning AI" title="It learns how your company bids"
            intro="Behind RevenueForge is a knowledge graph of your own company: what you can do, who can do it, where you have done it before and what it costs. Prompts can be copied. Your deal history can't." />
          <Reveal as="dl" className="mt-10 grid sm:grid-cols-2 gap-x-8 gap-y-8">
            {SIGNALS.map(([t, d]) => (
              <div key={t}>
                <dt className="text-[15.5px] font-semibold text-ink">{t}</dt>
                <dd className="mt-1.5 text-[14.5px] text-ink-soft leading-relaxed">{d}</dd>
              </div>
            ))}
          </Reveal>
        </div>
        <Reveal as="figure" className="rounded-2xl bg-white border border-line/70 shadow-lift p-6 md:p-8 lg:sticky lg:top-28">
          <figcaption className="text-[13px] font-semibold text-ink-muted">How one requirement reaches the price</figcaption>
          <ol className="mt-5 relative">
            <span aria-hidden className="absolute left-[7px] top-2 bottom-2 w-px bg-gradient-to-b from-brand-900 via-brand-300 to-brand-900" />
            {CHAIN.map((c, i) => {
              const end = i === 0 || i === CHAIN.length - 1;
              return (
                <li key={c} className="relative flex items-center gap-4 py-[7px]">
                  <span className={clsx("relative h-[15px] w-[15px] rounded-full border-2 shrink-0", end ? "bg-brand-900 border-brand-900" : "bg-white border-brand-400")} />
                  <span className={clsx("text-[15px]", end ? "font-semibold text-brand-950" : "text-ink-soft")}>{c}</span>
                  {i === 0 && <span className="ml-auto text-[12px] text-ink-faint">from the RFP</span>}
                  {i === CHAIN.length - 1 && <span className="ml-auto text-[12px] text-ink-faint">to the price</span>}
                </li>
              );
            })}
          </ol>
        </Reveal>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- security
const SECURITY: [typeof EyeOff, string, string][] = [
  [EyeOff, "Client names masked", "Turn on masking per deal and the client's name never appears in screens, AI prompts or documents."],
  [Lock, "Your workspace only", "Each company's capabilities, people, rates and RFPs are isolated. No one else can see or learn from them."],
  [FileSearch, "Every claim has a source", "Requirements link to their page in the RFP. Responses cite your real capabilities, case studies and people."],
  [ShieldCheck, "Your choice of AI", "Run on Gemini, Claude, OpenAI or Azure OpenAI. With masking on, client names never reach the AI."],
];

function Security() {
  return (
    <section id="security" className="scroll-mt-24 bg-paper">
      <div className={clsx(WRAP, SECTION)}>
        <SectionHeading eyebrow="Security" title="Built for confidential bids"
          intro="RFPs carry client names, pricing and strategy. RevenueForge is designed so that none of it leaves your workspace without your say." />
        <div className="mt-12 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {SECURITY.map(([Icon, t, d], i) => (
            <Reveal key={t} delay={i * 80} className="card card-hover p-6">
              <span className="h-11 w-11 rounded-xl bg-gradient-to-b from-brand-50 to-white border border-brand-100 text-brand-700 grid place-items-center shadow-[0_8px_20px_-12px_rgba(17,138,195,.6)]"><Icon className="h-5 w-5" aria-hidden /></span>
              <h3 className="mt-5 text-[16px] font-semibold text-ink">{t}</h3>
              <p className="mt-2 text-[14.5px] text-ink-soft leading-relaxed">{d}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- before / after
const COMPARE: [string, string, string][] = [
  ["RFP to first draft", "Days to weeks", "Hours"],
  ["Requirement extraction", "Manual reading and spreadsheets", "Automatic, classified, traceable to the source page"],
  ["Estimates", "Vary by author", "Grounded in your rate card, team and past deals"],
  ["Knowledge reuse", "In people's heads and old decks", "A knowledge graph that improves with every deal"],
  ["Handoff to delivery", "Context lost", "A structured pack: scope, assumptions, risks, team, plan"],
];

function Compare() {
  return (
    <section id="compare" className="scroll-mt-24 bg-paper">
      <div className={clsx(WRAP, SECTION)}>
        <SectionHeading eyebrow="Why RevenueForge" title="Before and after" intro="What changes for a pre-sales team on its next bid." />
        <Reveal className="mt-10 rounded-2xl border border-line/80 bg-white shadow-card overflow-x-auto">
          <table className="w-full min-w-[620px] text-[14.5px] text-left">
            <thead>
              <tr className="text-[13px]">
                <th scope="col" className="w-[24%] px-5 py-3.5 font-semibold text-ink-muted bg-[#F8FAFB]"><span className="sr-only">Area</span></th>
                <th scope="col" className="w-[32%] px-5 py-3.5 font-semibold text-ink-muted bg-[#F8FAFB]">Today</th>
                <th scope="col" className="px-5 py-3.5 font-semibold text-brand-800 bg-brand-50">With RevenueForge</th>
              </tr>
            </thead>
            <tbody>
              {COMPARE.map(([a, b, c]) => (
                <tr key={a} className="border-t border-line">
                  <th scope="row" className="px-5 py-4 font-semibold text-ink align-top">{a}</th>
                  <td className="px-5 py-4 text-ink-muted align-top">{b}</td>
                  <td className="px-5 py-4 text-ink bg-brand-50/50 align-top">
                    <span className="flex items-start gap-2.5"><Check className="h-4 w-4 mt-[3px] shrink-0 text-brand-600" strokeWidth={2.5} aria-hidden />{c}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Reveal>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- close
function ClosingCta() {
  const { user } = useAuth();
  return (
    <section className="bg-paper"><div className={clsx(WRAP, "pb-20 md:pb-28")}>
      <Reveal className="relative overflow-hidden rounded-[28px] stage-dark shadow-float px-6 py-14 md:px-14 md:py-20 grid md:grid-cols-[minmax(0,1fr)_auto] gap-8 md:items-center">
        <div aria-hidden className="absolute inset-0 grid-lines" />
        <div aria-hidden className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-ember-500/20 blur-3xl drift" />
        <div className="relative">
          <h2 className="font-display font-medium text-white text-[30px] md:text-[42px] leading-[1.15] tracking-[-0.01em] text-balance">Set up your workspace in about fifteen minutes.</h2>
          <p className="mt-3 text-[16.5px] leading-relaxed text-brand-100/80 max-w-xl">Upload your capabilities, skills matrix, rate card and proposal template. Then drop in your next RFP.</p>
        </div>
        <div className="relative flex flex-col sm:flex-row gap-3">
          {user ? (
            <Link to="/app" className="btn btn-lg bg-white text-brand-950 hover:bg-brand-50">Open workspace</Link>
          ) : (
            <>
              <Link to="/signup" className="btn btn-lg bg-white text-brand-950 hover:bg-brand-50">Create workspace</Link>
              <Link to="/login" className="btn btn-lg border border-white/25 text-white hover:bg-white/10">Sign in</Link>
            </>
          )}
        </div>
      </Reveal>
    </div></section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-line/70 bg-white">
      <div className={clsx(WRAP, "py-12 grid gap-10 md:grid-cols-[minmax(0,1.4fr)_repeat(2,minmax(0,1fr))]")}>
        <div>
          <ProductMark />
          <p className="mt-4 text-[14px] text-ink-muted leading-relaxed max-w-xs">From RFP to signed-off proposal and delivery handoff, grounded in what your company has actually delivered.</p>
        </div>
        <nav aria-label="Product">
          <div className="text-[13px] font-semibold text-ink">Product</div>
          <ul className="mt-3 space-y-2 text-[14px] text-ink-muted">
            {NAV.map(([href, label]) => <li key={href}><a href={href} className="hover:text-brand-950">{label}</a></li>)}
          </ul>
        </nav>
        <nav aria-label="Account">
          <div className="text-[13px] font-semibold text-ink">Account</div>
          <ul className="mt-3 space-y-2 text-[14px] text-ink-muted">
            <li><Link to="/signup" className="hover:text-brand-950">Create workspace</Link></li>
            <li><Link to="/login" className="hover:text-brand-950">Sign in</Link></li>
          </ul>
        </nav>
      </div>
      <div className="border-t border-line">
        <div className={clsx(WRAP, "py-5 text-[13px] text-ink-faint")}>© {new Date().getFullYear()} RevenueForge</div>
      </div>
    </footer>
  );
}

export default function Landing() {
  return (
    <div className="bg-white">
      <Header />
      <main>
        <Hero />
        <WholeBid />
        <HowItWorks />
        <Learning />
        <Security />
        <Compare />
        <ClosingCta />
      </main>
      <Footer />
      <LandingAssistant />
    </div>
  );
}
