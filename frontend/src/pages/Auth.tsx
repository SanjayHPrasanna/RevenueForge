import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { GoogleButton, MicrosoftButton, NoticeBar, OrDivider } from "../components/GoogleButton";
import clsx from "clsx";
import { ProductMark, Spinner } from "../components/ui";
import { useTilt } from "../components/motion";
import { useAuth } from "../lib/auth";

/** A small illustrative panel floating in perspective on the dark side of the sign-in page. Decorative only. */
function AuthPreview() {
  const tilt = useTilt<HTMLDivElement>(5, [10, -12]);
  const tiles = "SSPGSCSPGPSSPCGSSPSPGSCPSPS";
  const col: Record<string, string> = { S: "bg-fit-strong", P: "bg-fit-partial", G: "bg-fit-gap", C: "border-[1.5px] border-fit-confirm" };
  return (
    <div aria-hidden className="perspective max-w-md">
      <div className="rise-3d" style={{ animationDelay: ".15s" }}>
        <div ref={tilt} className="tilt tilt-glare rounded-2xl bg-white/[.07] border border-white/15 backdrop-blur-xl p-5 shadow-float">
          <div className="flex items-center justify-between text-[12px] text-brand-100/80">
            <span className="font-semibold text-white">Coverage map</span><span className="num">85 requirements</span>
          </div>
          <div className="mt-4 grid grid-cols-9 gap-1.5">
            {tiles.split("").map((c, i) => <span key={i} className={clsx("h-5 rounded-[4px]", col[c])} />)}
          </div>
          <div className="mt-5 flex items-end justify-between">
            <div><div className="text-[11px] uppercase tracking-[0.08em] text-brand-100/60">Bid readiness</div><div className="font-display num text-[30px] leading-none mt-1">84%</div></div>
            <div className="text-right"><div className="text-[11px] uppercase tracking-[0.08em] text-brand-100/60">Margin</div><div className="font-display num text-[30px] leading-none mt-1 text-ember-400">28%</div></div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Frame({ title, sub, children }: { title: string; sub: ReactNode; children: ReactNode }) {
  return (
    <div className="min-h-screen grid lg:grid-cols-[1fr_1.1fr] bg-white">
      <div className="hidden lg:flex relative overflow-hidden flex-col justify-between stage-dark text-white p-10">
        <div aria-hidden className="absolute inset-0 grid-lines" />
        <div aria-hidden className="absolute -right-32 top-1/4 h-96 w-96 rounded-full bg-brand-500/25 blur-[100px] drift" />
        <div className="relative"><ProductMark white /></div>
        <div className="relative">
          <AuthPreview />
          <div className="mt-12 font-display font-medium text-[38px] xl:text-[44px] leading-[1.05] tracking-[-0.03em] max-w-md text-balance">Your company's deal knowledge, working on every RFP.</div>
          <p className="text-brand-100/75 mt-5 max-w-md leading-relaxed text-[15.5px]">
            Requirements traced to the page. Matches backed by real capabilities, people and references. Proposals in your own template.
          </p>
        </div>
        <div className="relative text-[12px] text-brand-100/55">Your data stays in your company's workspace.</div>
      </div>
      <div className="flex items-center justify-center p-6 ambient">
        <div className="w-full max-w-[400px] page-enter">
          <div className="lg:hidden mb-8">
            <ProductMark />
          </div>
          <NoticeBar className="rounded-lg border mb-6 text-left" />
          <h1 className="font-display text-[38px] leading-[1.05] tracking-[-0.025em] text-brand-950">{title}</h1>
          <div className="text-ink-muted text-sm mt-1 mb-7">{sub}</div>
          {children}
        </div>
      </div>
    </div>
  );
}

export function Login() {
  const { login, google, microsoft } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(sp.get("expired") ? "Your session expired. Sign in again." : "");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await login(email, password);
      nav(sp.get("next") || "/app");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const withGoogle = async (credential: string) => {
    setErr("");
    try {
      const r = await google(credential);
      if (r.needs_company) nav("/signup", { state: { google: { credential, email: r.email, name: r.name } } });
      else nav(sp.get("next") || "/app");
    } catch (e: any) {
      setErr(e.message);
    }
  };
  const withMicrosoft = async (credential: string, nonce: string) => {
    setErr("");
    try {
      const r = await microsoft(credential, nonce);
      if (r.needs_company) nav("/signup", { state: { google: { credential, nonce, provider: "microsoft", email: r.email, name: r.name } } });
      else nav(sp.get("next") || "/app");
    } catch (e: any) {
      setErr(e.message);
    }
  };
  return (
    <Frame title="Sign in" sub={<>New to RevenueForge? <Link className="text-brand-600 font-semibold" to="/signup">Create a company workspace</Link></>}>
      <MicrosoftButton onCredential={withMicrosoft} />
      <GoogleButton onCredential={withGoogle} text="signin_with" />
      <OrDivider label="or with your email" />
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="email">Work email</label>
          <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="pw">Password</label>
          <input id="pw" className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {err && <div className="text-sm text-fit-gap-ink">{err}</div>}
        <button className="btn-primary w-full h-10" disabled={busy}>{busy && <Spinner />} Sign in</button>
      </form>
    </Frame>
  );
}

export function Signup() {
  const { register, google, microsoft } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [g, setG] = useState<{ credential: string; email: string; name: string; provider?: "google" | "microsoft"; nonce?: string } | null>((loc.state as any)?.google || null);
  const [f, setF] = useState({ company_name: "", industry: "", headquarters: "", name: "", email: "", password: "", kind: new URLSearchParams(loc.search).get("as") === "buyer" ? "buyer" : "vendor" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const after = (u?: any) => nav(f.kind === "buyer" || u?.tenant?.kind === "buyer" ? "/app/buyer" : u && Object.keys(u.tenant.onboarding || {}).length ? "/app" : "/onboarding");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      if (g) {
        const company = { company_name: f.company_name, industry: f.industry, headquarters: f.headquarters, kind: f.kind };
        const r = g.provider === "microsoft" ? await microsoft(g.credential, g.nonce || "", company) : await google(g.credential, company);
        if (r.needs_company) throw new Error("Enter your company name.");
        after(r.user);
      } else {
        after(await register(f));
      }
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const withGoogle = async (credential: string) => {
    setErr("");
    try {
      const r = await google(credential);
      if (r.needs_company) setG({ credential, email: r.email!, name: r.name! });
      else nav("/app");  // already had an account: signed straight in
    } catch (e: any) {
      setErr(e.message);
    }
  };
  const withMicrosoft = async (credential: string, nonce: string) => {
    setErr("");
    try {
      const r = await microsoft(credential, nonce);
      if (r.needs_company) setG({ credential, nonce, provider: "microsoft", email: r.email!, name: r.name! });
      else nav("/app");
    } catch (e: any) {
      setErr(e.message);
    }
  };
  return (
    <Frame title="Create your company workspace" sub={<>Already have one? <Link className="text-brand-600 font-semibold" to="/login">Sign in</Link></>}>
      {!g && <><MicrosoftButton onCredential={withMicrosoft} label="Sign up with Microsoft" /><GoogleButton onCredential={withGoogle} text="signup_with" /><OrDivider label="or sign up with your email" /></>}
      {g && (
        <div className="rounded-md border border-line bg-paper px-4 py-3 mb-5 text-[13.5px]">
          <div className="text-ink-muted">Signing up with {g.provider === "microsoft" ? "Microsoft" : "Google"} as</div>
          <div className="font-semibold">{g.name} <span className="font-normal text-ink-muted">({g.email})</span></div>
          <button type="button" className="text-[12.5px] text-brand-700 font-semibold mt-1" onClick={() => setG(null)}>Use a different method</button>
        </div>
      )}
      <form onSubmit={submit} className="space-y-4">
        <fieldset>
          <legend className="label">This workspace is for</legend>
          <div className="grid grid-cols-2 gap-2">
            {[["vendor", "Winning work", "We bid on RFPs and tenders"], ["buyer", "Buying", "We issue RFPs and find suppliers"]].map(([k, l, d]) => (
              <label key={k} className={`cursor-pointer rounded-lg border px-3 py-2.5 transition-colors ${f.kind === k ? "border-brand-500 bg-brand-50" : "border-line hover:border-brand-200"}`}>
                <input type="radio" name="kind" value={k} checked={f.kind === k} onChange={() => setF({ ...f, kind: k })} className="sr-only" />
                <span className="block font-semibold text-[13.5px]">{l}</span><span className="block text-[12px] text-ink-muted">{d}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div>
          <label className="label" htmlFor="cn">{f.kind === "buyer" ? "Organisation name" : "Company name"}</label>
          <input id="cn" className="input" required value={f.company_name} onChange={set("company_name")} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="ind">Industry</label>
            <input id="ind" className="input" placeholder="e.g. IT services" value={f.industry} onChange={set("industry")} />
          </div>
          <div>
            <label className="label" htmlFor="hq">Headquarters</label>
            <input id="hq" className="input" placeholder="City, country" value={f.headquarters} onChange={set("headquarters")} />
          </div>
        </div>
        {!g && <>
        <div className="pt-2 border-t border-line-soft" />
        <div>
          <label className="label" htmlFor="nm">Your name</label>
          <input id="nm" className="input" required autoComplete="name" value={f.name} onChange={set("name")} />
        </div>
        <div>
          <label className="label" htmlFor="em">Work email</label>
          <input id="em" className="input" type="email" required autoComplete="email" value={f.email} onChange={set("email")} />
        </div>
        <div>
          <label className="label" htmlFor="pw">Password</label>
          <input id="pw" className="input" type="password" minLength={8} required autoComplete="new-password" value={f.password} onChange={set("password")} />
          <div className="text-[12px] text-ink-muted mt-1">At least 8 characters.</div>
        </div>
        </>}
        {err && <div className="text-sm text-fit-gap-ink">{err}</div>}
        <button className="btn-primary w-full h-10" disabled={busy}>{busy && <Spinner />} Create workspace</button>
        <p className="text-[12px] text-ink-muted">You'll be the admin of this workspace. {f.kind === "buyer" ? "Next, you'll upload an RFP and see which suppliers can deliver it." : "Next, you'll upload your company pack."}</p>
      </form>
    </Frame>
  );
}
