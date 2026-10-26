import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
import Dashboard from "./pages/Dashboard";
import DealWorkspace from "./pages/DealWorkspace";
import Deals from "./pages/Deals";
import GraphPage from "./pages/Graph";
import Landing from "./pages/Landing";
import Learning from "./pages/Learning";
import Library from "./pages/Library";
import { Login, Signup } from "./pages/Auth";
import { MicrosoftCallback } from "./components/GoogleButton";
import Onboarding from "./pages/Onboarding";
import SettingsPage from "./pages/Settings";
import WinLoss from "./pages/WinLoss";

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1, staleTime: 5_000 } } });

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
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/auth/microsoft" element={<MicrosoftCallback />} />
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
                <Route path="settings" element={<SettingsPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
          </TipProvider>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
