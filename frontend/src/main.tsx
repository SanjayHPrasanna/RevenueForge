import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Shell from "./components/Shell";
import { PageLoader, ToastProvider } from "./components/ui";
import { TipProvider } from "./components/viz";
import "@fontsource-variable/hanken-grotesk";
import "@fontsource-variable/newsreader";
import "./index.css";
import { AuthProvider, useAuth } from "./lib/auth";
import { PAGES } from "./lib/prefetch";
import Landing from "./pages/Landing";
import { Login, Signup } from "./pages/Auth";
import { MicrosoftCallback } from "./components/GoogleButton";

// The workspace pages load on demand, so the landing page downloads only what it shows.
const Dashboard = React.lazy(() => PAGES.dashboard());
const DealWorkspace = React.lazy(() => PAGES.deal());
const Deals = React.lazy(() => PAGES.deals());
const GraphPage = React.lazy(() => PAGES.graph());
const Learning = React.lazy(() => PAGES.learning());
const Library = React.lazy(() => PAGES.library());
const Onboarding = React.lazy(() => PAGES.onboarding());
const SettingsPage = React.lazy(() => PAGES.settings());
const WinLoss = React.lazy(() => PAGES.winloss());
const RadarPage = React.lazy(() => PAGES.radar());
const Market = React.lazy(() => PAGES.market());
const Customers = React.lazy(() => PAGES.customers());
const Platform = React.lazy(() => PAGES.platform());
const CalendarPage = React.lazy(() => PAGES.calendar());
const TrustPage = React.lazy(() => PAGES.trust().then((m) => ({ default: m.TrustPage })));
const PrivacyPage = React.lazy(() => PAGES.trust().then((m) => ({ default: m.PrivacyPage })));
const TermsPage = React.lazy(() => PAGES.trust().then((m) => ({ default: m.TermsPage })));
const BuyerRequests = React.lazy(() => PAGES.buyer().then((m) => ({ default: m.BuyerRequests })));
const BuyerRequest = React.lazy(() => PAGES.buyer().then((m) => ({ default: m.BuyerRequest })));

/** Shown for addresses that don't exist, instead of silently jumping to the home page. */
function NotFound() {
  return (
    <main className="min-h-screen grid place-items-center bg-paper px-4">
      <div className="text-center max-w-md">
        <div className="eyebrow mb-2">Page not found</div>
        <h1 className="font-display text-[34px] leading-tight text-brand-950">We couldn't find that page</h1>
        <p className="text-ink-muted text-[14px] mt-2">The link may be old or mistyped.</p>
        <div className="mt-6 flex justify-center gap-2">
          <a href="/" className="btn-outline">Home</a>
          <a href="/app" className="btn-primary">Open workspace</a>
        </div>
      </div>
    </main>
  );
}

// Data stays fresh for 30 s, so going back to a page shows it at once instead of reloading it. After any change
// (approve, upload, edit...), the summary lists are marked old so they show the change next time they appear.
const SUMMARIES = [["deals"], ["dashboard"], ["reminders"], ["calendar"]];
const qc: QueryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1, staleTime: 30_000 } },
  mutationCache: new MutationCache({ onSuccess: () => SUMMARIES.forEach((k) => qc.invalidateQueries({ queryKey: k, refetchType: "active" })) }),
});

function Private({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <PageLoader />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />;
  return <>{children}</>;
}

function Public({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <PageLoader />;
  if (user) return <Navigate to="/app" replace />;
  return <>{children}</>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <ToastProvider>
          <TipProvider>
          <BrowserRouter future={{ v7_startTransition: true }}>
            <React.Suspense fallback={<PageLoader />}>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/auth/microsoft" element={<MicrosoftCallback />} />
              <Route path="/trust" element={<TrustPage />} />
              <Route path="/privacy" element={<PrivacyPage />} />
              <Route path="/terms" element={<TermsPage />} />
              <Route path="/login" element={<Public><Login /></Public>} />
              <Route path="/signup" element={<Public><Signup /></Public>} />
              <Route path="/onboarding" element={<Private><Onboarding /></Private>} />
              <Route path="/app" element={<Private><Shell /></Private>}>
                <Route index element={<Dashboard />} />
                <Route path="deals" element={<Deals />} />
                <Route path="deals/:id" element={<DealWorkspace />} />
                <Route path="deals/:id/:stage" element={<DealWorkspace />} />
                <Route path="library" element={<Library />} />
                <Route path="library/:kind" element={<Library />} />
                <Route path="graph" element={<GraphPage />} />
                <Route path="learning" element={<Learning />} />
                <Route path="winloss" element={<WinLoss />} />
                <Route path="opportunities" element={<RadarPage />} />
                <Route path="market" element={<Market />} />
                <Route path="customers" element={<Customers />} />
                <Route path="platform" element={<Platform />} />
                <Route path="calendar" element={<CalendarPage />} />
                <Route path="buyer" element={<BuyerRequests />} />
                <Route path="buyer/:id" element={<BuyerRequest />} />
                <Route path="settings" element={<SettingsPage />} />
              </Route>
              <Route path="*" element={<NotFound />} />
            </Routes>
            </React.Suspense>
          </BrowserRouter>
          </TipProvider>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
