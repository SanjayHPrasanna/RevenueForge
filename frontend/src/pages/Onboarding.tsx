import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Check, FolderUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import FolderImport from "../components/FolderImport";
import UploadReview, { KIND_INFO, TemplateUpload } from "../components/UploadReview";
import { PageLoader, ProductMark, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";

const STEPS = [
  { key: "profile", title: "Company profile" },
  { key: "capabilities", title: "Capabilities" },
  { key: "skills", title: "Skills matrix" },
  { key: "certifications", title: "Certifications" },
  { key: "rates", title: "Rate card" },
  { key: "case_studies", title: "Case studies" },
  { key: "template", title: "Proposal template" },
];

function Profile({ company, onSaved }: { company: any; onSaved: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [f, setF] = useState({ name: company.name, industry: company.industry, website: company.website, headquarters: company.headquarters,
    headcount: company.headcount || "", founded: company.founded, currency: company.currency || "USD", about: company.about });
  const save = useMutation({
    mutationFn: () => api.put("/company", f),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["company"] }); toast("ok", "Profile saved."); onSaved(); },
    onError: (e: any) => toast("error", e.message),
  });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <p className="text-ink-soft text-[14.5px]">Used in proposal boilerplate (“About us”) and to judge industry fit.</p>
      <div className="grid sm:grid-cols-2 gap-4">
        <div><label className="label">Company name</label><input className="input" value={f.name} onChange={set("name")} required /></div>
        <div><label className="label">Industry</label><input className="input" value={f.industry} onChange={set("industry")} placeholder="e.g. IT services – integration" required /></div>
        <div><label className="label">Headquarters</label><input className="input" value={f.headquarters} onChange={set("headquarters")} /></div>
        <div><label className="label">Website</label><input className="input" value={f.website} onChange={set("website")} /></div>
        <div><label className="label">Headcount</label><input className="input num" type="number" value={f.headcount} onChange={set("headcount")} /></div>
        <div><label className="label">Rate card currency</label>
          <select className="input" value={f.currency} onChange={set("currency")}>{["USD", "INR", "AED", "EUR", "GBP", "SAR", "KWD"].map((c) => <option key={c}>{c}</option>)}</select>
        </div>
      </div>
      <div>
        <label className="label">About the company</label>
        <textarea className="input h-28 py-2" value={f.about} onChange={set("about")} required placeholder="Two or three sentences a client would read in a proposal." />
      </div>
      <button className="btn-primary" disabled={save.isPending}>{save.isPending && <Spinner />} Save and continue</button>
    </form>
  );
}

export default function Onboarding() {
  const nav = useNavigate();
  const { data: company, isLoading } = useQuery({ queryKey: ["company"], queryFn: () => api.get("/company") });
  const [step, setStep] = useState<string | null>(null);
  useEffect(() => {
    if (company && step === null) {
      const st = company.onboarding.steps;
      const fresh = !["capabilities", "skills", "rates", "template"].some((k) => st[k]);
      const first = STEPS.find((s) => !st[s.key]);
      setStep(fresh ? "folder" : first?.key || "profile");
    }
  }, [company, step]);
  if (isLoading || !company || !step) return <PageLoader />;
  const steps = company.onboarding.steps;
  const idx = STEPS.findIndex((s) => s.key === step);
  // jump to the next step that still needs something; when nothing is left, setup is finished
  const nextOpen = (after: number, justDone?: string) =>
    STEPS.slice(after + 1).concat(STEPS.slice(0, Math.max(after, 0))).find((s) => s.key !== justDone && !steps[s.key]);
  const next = (justDone?: string) => {
    const n = nextOpen(idx, justDone);
    n ? setStep(n.key) : nav("/app");
  };
  const firstOpen = () => {
    const n = STEPS.find((s) => !steps[s.key]);
    n ? setStep(n.key) : nav("/app");
  };
  const cur = STEPS[Math.max(idx, 0)];
  const required = company.onboarding.required as string[];

  return (
    <div className="min-h-screen bg-paper">
      <header className="h-16 bg-white border-b border-line flex items-center px-4 md:px-8">
        <ProductMark />
        <div className="flex-1" />
        <Link to="/app" className="btn-ghost">Go to workspace</Link>
      </header>
      <div className="max-w-6xl mx-auto px-4 md:px-8 py-8 grid md:grid-cols-[240px_1fr] gap-8">
        <aside>
          <div className="text-[13px] font-semibold text-ink-muted mb-3">Set up {company.name}</div>
          <button
            onClick={() => setStep("folder")}
            className={clsx("w-full mb-3 flex items-center gap-3 rounded-lg px-2.5 py-2.5 text-left border transition-colors",
              step === "folder" ? "bg-white shadow-card border-brand-200" : "bg-brand-50/70 border-brand-100 hover:bg-white")}
          >
            <span className="h-6 w-6 rounded-full grid place-items-center bg-brand-500 text-white shrink-0"><FolderUp className="h-3.5 w-3.5" /></span>
            <span className="flex-1 min-w-0">
              <span className="block text-[14px] font-semibold text-brand-900">Import a whole folder</span>
              <span className="block text-[11.5px] text-ink-muted">Fastest: every file at once</span>
            </span>
          </button>
          <div className="text-[11.5px] uppercase tracking-wide font-semibold text-ink-faint mb-1.5 px-1">Or one at a time</div>
          <ol className="space-y-1">
            {STEPS.map((s, i) => (
              <li key={s.key}>
                <button
                  onClick={() => setStep(s.key)}
                  className={clsx("w-full flex items-center gap-3 rounded-md px-2.5 h-10 text-left text-[14px]", s.key === step ? "bg-white shadow-card font-semibold" : "hover:bg-white/60")}
                >
                  <span className={clsx("h-6 w-6 rounded-full grid place-items-center text-[11px] font-bold shrink-0",
                    steps[s.key] ? "bg-ok text-white" : s.key === step ? "bg-brand-500 text-white" : "bg-line text-ink-muted")}>
                    {steps[s.key] ? <Check className="h-3.5 w-3.5" /> : i + 1}
                  </span>
                  <span className="flex-1">{s.title}</span>
                  {required.includes(s.key) && !steps[s.key] && <span className="text-[10.5px] text-ember-600 font-semibold">Required</span>}
                </button>
              </li>
            ))}
          </ol>
          {company.onboarding.complete && (
            <div className="mt-5 rounded-lg border border-ok/30 bg-ok-bg/70 p-3">
              <div className="text-[13.5px] font-semibold text-ok flex items-center gap-1.5"><Check className="h-4 w-4" /> Ready to bid</div>
              <div className="text-[12.5px] text-ink-soft mt-1">Everything required is in. Add the rest any time from the Knowledge library.</div>
              <button className="btn-ember w-full mt-3" onClick={() => nav("/app")}>Finish setup <ArrowRight className="h-4 w-4" /></button>
            </div>
          )}
          <div className="mt-6 text-[12.5px] text-ink-muted leading-relaxed">
            Everything you upload stays in your workspace and builds your private knowledge graph. You can update any of it later from the Knowledge library.
          </div>
        </aside>
        {step === "folder" ? (
          <section className="card p-6 md:p-8 min-w-0">
            <div className="text-[12.5px] text-ink-muted">Fastest way to set up</div>
            <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950 mt-1 mb-2">Bring in everything at once</h1>
            <p className="text-ink-soft text-[14.5px] mb-5">No need to upload files one by one. Point RevenueForge at the folder where your company knowledge lives, check what it found, and import it all in one go. You can still fix or add single files afterwards.</p>
            <FolderImport onDone={firstOpen} />
            <div className="mt-6 pt-5 border-t border-line-soft flex items-center">
              <div className="flex-1" />
              <button className="btn-outline" onClick={() => setStep("profile")}>Set up step by step instead <ArrowRight className="h-4 w-4" /></button>
            </div>
          </section>
        ) : (
        <section className="card p-6 md:p-8 min-w-0">
          <div className="text-[12.5px] text-ink-muted num">Step {idx + 1} of {STEPS.length}</div>
          <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950 mt-1 mb-4">{cur.key === "profile" ? "Tell us about your company" : cur.key === "template" ? "Your proposal template" : KIND_INFO[cur.key].title}</h1>
          {cur.key === "profile" ? (
            <Profile company={company} onSaved={() => next("profile")} />
          ) : cur.key === "template" ? (
            <TemplateUpload />
          ) : (
            <UploadReview key={cur.key} kind={cur.key} />
          )}
          {cur.key !== "profile" && (
            <div className="mt-8 pt-5 border-t border-line-soft flex items-center gap-3">
              {steps[cur.key] && <span className="text-[13px] text-ok font-semibold flex items-center gap-1.5"><Check className="h-4 w-4" /> {company.onboarding.counts[cur.key] ?? ""} in your library</span>}
              <div className="flex-1" />
              {company.onboarding.complete ? (
                <>
                  {nextOpen(idx) && <button className="btn-outline" onClick={() => next()}>Next: {nextOpen(idx)!.title}</button>}
                  <button className="btn-ember" onClick={() => nav("/app")}>Finish setup <ArrowRight className="h-4 w-4" /></button>
                </>
              ) : (
                <button className="btn-outline" onClick={() => next()}>
                  {steps[cur.key] || !required.includes(cur.key) ? `Next${nextOpen(idx) ? `: ${nextOpen(idx)!.title}` : ""}` : "Skip for now"} <ArrowRight className="h-4 w-4" />
                </button>
              )}
            </div>
          )}
        </section>
        )}
      </div>
    </div>
  );
}
