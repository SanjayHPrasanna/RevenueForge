import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, CircleDashed, ExternalLink, Scale, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { PageLoader } from "../components/ui";
import { api } from "../lib/api";

/* Trust & data, Privacy policy and Terms of use. The facts (who runs the service, where data is stored, which AI is used,
   which outside services are involved, what isn't in place yet) come from /api/trust, which reads the server's real setup. */

type Trust = {
  operator: string; contact: string; updated: string; data_location: string;
  ai: { enabled: boolean; provider?: string; terms_url?: string; paid?: boolean | null; training?: string; summary: string };
  company_ai_note: string;
  subprocessors: { name: string; purpose: string; where: string }[];
  sources: { name: string; covers: string; licence: string; licence_url: string; attribution: string; enabled: boolean }[];
  in_place: string[]; not_yet: string[]; fairness: string[];
};

const useTrust = () => useQuery({ queryKey: ["trust"], queryFn: () => api.get<Trust>("/trust"), staleTime: 60_000 });

function Page({ title, eyebrow, children }: { title: string; eyebrow: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-paper">
      <header className="border-b border-line bg-white">
        <div className="max-w-[920px] mx-auto px-6 h-14 flex items-center gap-4 text-[14px]">
          <Link to="/" className="inline-flex items-center gap-1.5 text-ink-muted hover:text-brand-900"><ArrowLeft className="h-4 w-4" /> RevenueForge</Link>
          <div className="flex-1" />
          <Link to="/trust" className="text-ink-muted hover:text-brand-900">Trust & data</Link>
          <Link to="/privacy" className="text-ink-muted hover:text-brand-900">Privacy</Link>
          <Link to="/terms" className="text-ink-muted hover:text-brand-900">Terms</Link>
        </div>
      </header>
      <main className="max-w-[920px] mx-auto px-6 py-10">
        <div className="eyebrow mb-1.5">{eyebrow}</div>
        <h1 className="font-display text-[38px] leading-[1.05] tracking-[-0.025em] text-brand-950">{title}</h1>
        <div className="mt-6 space-y-7 text-[15px] leading-relaxed text-ink-soft">{children}</div>
      </main>
    </div>
  );
}

function H({ children }: { children: ReactNode }) {
  return <h2 className="font-semibold text-[19px] text-ink mt-2 mb-2">{children}</h2>;
}

function contact(t: Trust) {
  return t.contact ? <a className="text-brand-700 underline" href={`mailto:${t.contact}`}>{t.contact}</a> : <span>the contact address the operator publishes</span>;
}

export function TrustPage() {
  const { data: t } = useTrust();
  if (!t) return <PageLoader />;
  return (
    <Page title="Trust & data" eyebrow={`Last updated ${t.updated}`}>
      <p>What happens to your data in RevenueForge, which outside services are involved, and what isn't in place yet. These facts are read
        from how this server is actually set up.</p>
      <section>
        <H>Where your data is stored</H>
        <p>{t.data_location ? <>Your company's data and files are stored on <b>{t.data_location}</b>.</> : <>Your data is stored with the hosting provider listed below.</>}{" "}
          Each company's data is kept separate from every other company's.</p>
      </section>
      <section>
        <H>AI</H>
        <p>{t.ai.summary}</p>
        {t.ai.training && <p className="mt-2 rounded-lg border border-line bg-white px-4 py-3 text-[14px]">{t.ai.training}
          {t.ai.terms_url && <> <a className="text-brand-700 underline inline-flex items-center gap-1" href={t.ai.terms_url} target="_blank" rel="noreferrer">Provider terms <ExternalLink className="h-3 w-3" /></a></>}</p>}
        <p className="mt-2">{t.company_ai_note}</p>
        <p className="mt-2">Nothing is decided by AI alone: every stage of a deal (requirements, matches, gaps, architecture, estimate, price,
          proposal, handoff) is reviewed and approved by a named person on your team before it's final.</p>
      </section>
      <section>
        <H>Outside services that handle data</H>
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[560px] text-[14px]">
            <thead><tr><th className="th">Service</th><th className="th">What for</th><th className="th">Where</th></tr></thead>
            <tbody>{t.subprocessors.map((s) => <tr key={s.name}><td className="td font-semibold">{s.name}</td><td className="td">{s.purpose}</td><td className="td">{s.where}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
      <section>
        <H><span className="inline-flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-ok" /> In place</span></H>
        <ul className="space-y-2">{t.in_place.map((x) => <li key={x} className="flex gap-2.5"><CheckCircle2 className="h-4 w-4 mt-1 shrink-0 text-ok" />{x}</li>)}</ul>
      </section>
      <section>
        <H><span className="inline-flex items-center gap-2"><CircleDashed className="h-5 w-5 text-fit-partial-ink" /> Not in place yet</span></H>
        <ul className="space-y-2">{t.not_yet.map((x) => <li key={x} className="flex gap-2.5"><CircleDashed className="h-4 w-4 mt-1 shrink-0 text-fit-partial-ink" />{x}</li>)}</ul>
      </section>
      <section>
        <H><span className="inline-flex items-center gap-2"><Scale className="h-5 w-5 text-brand-600" /> Fairness</span></H>
        <ul className="space-y-2 list-disc pl-5">{t.fairness.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>
      <section>
        <H>Public tender data</H>
        <p className="mb-3">Opportunities come from these open-data sources, reused under their licences. Summaries are shortened and personal
          contact details are removed before storing; each tender links to the original notice.</p>
        <div className="space-y-2">
          {t.sources.map((s) => (
            <div key={s.name} className="rounded-lg border border-line bg-white px-4 py-3 text-[14px]">
              <div className="font-semibold">{s.name}{!s.enabled && <span className="ml-2 text-[12px] font-normal text-ink-muted">(not switched on)</span>}</div>
              <div className="text-ink-muted">{s.covers}</div>
              <div className="mt-1"><a className="text-brand-700 underline" href={s.licence_url} target="_blank" rel="noreferrer">{s.licence}</a> · {s.attribution}</div>
            </div>
          ))}
        </div>
      </section>
      <section>
        <H>Your rights and requests</H>
        <p>A company admin can download all of the company's data, or delete it permanently, from <b>Settings → Your company's data</b>.
          For anything else (a copy of your personal data, a correction, a complaint), contact {t.operator} at {contact(t)}.</p>
      </section>
    </Page>
  );
}

export function PrivacyPage() {
  const { data: t } = useTrust();
  if (!t) return <PageLoader />;
  return (
    <Page title="Privacy policy" eyebrow={`Last updated ${t.updated}`}>
      <p>This policy explains how {t.operator} ("we") handles personal data in RevenueForge. It is written to meet India's Digital Personal Data
        Protection Act, 2023 and, for people in the EU and UK, the GDPR.</p>
      <section>
        <H>Two kinds of data</H>
        <p><b>Your account.</b> When you sign up or are invited we keep your name, work email, role, company, and a salted hash of your password
          (or the id of the Google or Microsoft account you sign in with). We decide how this is used, for running your account.</p>
        <p className="mt-2"><b>What your company puts in.</b> RFPs, proposals, the knowledge library (including people's skills, grades and
          locations), comments and deal outcomes belong to your company. We process them only to provide the service, on your company's
          instructions. Your company decides what goes in and who sees it.</p>
      </section>
      <section>
        <H>What we use it for</H>
        <ul className="list-disc pl-5 space-y-1">
          <li>Signing you in, keeping companies separate and enforcing roles.</li>
          <li>Reading RFPs, matching them to your library, and drafting estimates, prices and documents for your team to review.</li>
          <li>Emails you've asked for (for example, "your deal is ready for review").</li>
          <li>Security: rate limits, an audit log of who did what, and investigating misuse.</li>
        </ul>
        <p className="mt-2">We don't sell personal data or show advertising. Corrections your team makes are used to improve suggestions for
          your company only; they're never shared with other companies or used to train a general AI model. Employee names in an imported
          skills matrix are hidden by default.</p>
      </section>
      <section>
        <H>Who else handles it</H>
        <p>The outside services listed on the <Link className="text-brand-700 underline" to="/trust">Trust & data</Link> page, only for the
          purpose shown there. {t.ai.enabled ? <>When AI is used, the part of a document being worked on is sent to {t.ai.provider}. {t.ai.training}</> : "No AI service is switched on at the moment."}</p>
        {t.data_location && <p className="mt-2">Data is stored on {t.data_location}. Some outside services may process data in other countries
          under their own safeguards.</p>}
      </section>
      <section>
        <H>How long we keep it</H>
        <p>For as long as your company uses RevenueForge. When a company admin deletes the company in Settings, its users, library, deals,
          files and audit log are deleted at once; we keep only a record that a deletion happened, without names or emails. Copies in hosting
          backups, where they exist, expire on the backup schedule.</p>
      </section>
      <section>
        <H>Your rights</H>
        <p>You can ask to see, correct or delete your personal data, withdraw consent, or nominate someone to act for you. If your data came
          from your company's library, we'll pass your request to your company, which decides on it. Write to {contact(t)}; we aim to reply
          within 30 days. If you aren't satisfied, you can complain to the Data Protection Board of India or, in the EU or UK, your data
          protection authority.</p>
      </section>
      <section>
        <H>Contact and grievances</H>
        <p>{t.operator}, {contact(t)}.</p>
      </section>
    </Page>
  );
}

export function TermsPage() {
  const { data: t } = useTrust();
  if (!t) return <PageLoader />;
  return (
    <Page title="Terms of use" eyebrow={`Last updated ${t.updated}`}>
      <p>These terms apply to using RevenueForge, provided by {t.operator}. By creating a workspace or accepting an invitation you agree to them
        on behalf of yourself and your company.</p>
      <section>
        <H>Your content</H>
        <p>Your company owns what it uploads and what RevenueForge generates for it. You confirm you're allowed to upload it, including any
          client RFP and any personal data in your library. You give us permission to process it only to provide the service.</p>
      </section>
      <section>
        <H>AI-assisted output needs your review</H>
        <p>Requirements, matches, estimates, prices and documents are drafts produced by rules and, when switched on, AI. They can be wrong or
          incomplete. Every stage has to be approved by someone on your team, and you are responsible for what you submit to a client.
          RevenueForge marks requirements it can't support as not covered rather than promising them; don't remove those markers without a real plan.</p>
        {t.ai.enabled && !t.ai.paid && t.ai.provider?.startsWith("Google") && (
          <p className="mt-2 rounded-lg border border-ember-100 bg-ember-50 px-4 py-3 text-[14px] text-ember-600">This server uses a free-tier AI key.
            Don't upload confidential client documents; the app asks you to confirm before each RFP.</p>
        )}
      </section>
      <section>
        <H>Opportunities and market insights</H>
        <p>Tender notices come from public sources under their own licences (listed on the <Link className="text-brand-700 underline" to="/trust">Trust
          & data</Link> page). Always read the official notice: deadlines and requirements there take precedence. Fit scores and market insights
          are estimates from the notice summary and your library.</p>
      </section>
      <section>
        <H>Supplier network</H>
        <p>Buyers see a supplier's public profile only if the supplier lists itself. Shortlists rank suppliers by evidence in their own libraries,
          the same way for everyone; they are advice, not a procurement decision, and don't replace a buyer's own procurement rules.
          Demo suppliers are fictional and labelled as such. When a supplier accepts an invitation, a copy of the buyer's RFP is placed in the
          supplier's workspace and processed with the supplier's own setup, including its own AI provider.</p>
      </section>
      <section>
        <H>Acceptable use</H>
        <p>Don't try to reach another company's data, overload or probe the service, upload malware, or use the service to break the law or
          someone else's rights. We may suspend accounts that do.</p>
      </section>
      <section>
        <H>Availability and liability</H>
        <p>We work to keep the service running and your data safe, but it is provided as it is, without a guarantee of uninterrupted availability.
          To the extent the law allows, we aren't liable for indirect losses or for decisions made using the output.</p>
      </section>
      <section>
        <H>Ending use</H>
        <p>A company admin can export all of the company's data and then delete the company in Settings at any time. Questions: {contact(t)}.</p>
      </section>
    </Page>
  );
}
