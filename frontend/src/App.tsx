import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "@/components/Layout";
import { ToastProvider } from "@/components/Toast";
import { Spinner } from "@/components/ui";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { ThemeProvider } from "@/hooks/useTheme";
import Login from "@/pages/Login";
import { Privacy, Terms } from "@/pages/Legal";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Channels = lazy(() => import("@/pages/Channels"));
const ReviewQueue = lazy(() => import("@/pages/ReviewQueue"));
const Published = lazy(() => import("@/pages/Published"));
const Skipped = lazy(() => import("@/pages/Skipped"));
const Integrations = lazy(() => import("@/pages/Integrations"));
const EditingRules = lazy(() => import("@/pages/EditingRules"));
const DailyReport = lazy(() => import("@/pages/DailyReport"));
const TikTokAccounts = lazy(() => import("@/pages/TikTokAccounts"));
const AutomationRules = lazy(() => import("@/pages/AutomationRules"));
const PromptStudio = lazy(() => import("@/pages/PromptStudio"));
const JobsQueue = lazy(() => import("@/pages/JobsQueue"));
const ComplianceAudit = lazy(() => import("@/pages/ComplianceAudit"));
const Logs = lazy(() => import("@/pages/Logs"));
const Settings = lazy(() => import("@/pages/Settings"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: (count, error) => count < 2 && !(error as { status?: number }).status?.toString().startsWith("4") } },
});

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="login-page"><Spinner/></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }}/>;
  return <>{children}</>;
}

export default function App() {
  return <QueryClientProvider client={queryClient}><BrowserRouter><AuthProvider><ThemeProvider><ToastProvider>
    <Routes>
      <Route path="/login" element={<Login/>}/>
      <Route path="/terms" element={<Terms/>}/>
      <Route path="/privacy" element={<Privacy/>}/>
      <Route element={<RequireAuth><Layout/></RequireAuth>}>
        {([["/", Dashboard], ["/channels", Channels], ["/review", ReviewQueue], ["/published", Published], ["/skipped", Skipped], ["/editing", EditingRules], ["/integrations", Integrations], ["/report", DailyReport], ["/tiktok", TikTokAccounts], ["/rules", AutomationRules], ["/prompts", PromptStudio], ["/jobs", JobsQueue], ["/audit", ComplianceAudit], ["/logs", Logs], ["/settings", Settings]] as const).map(([path, Page]) =>
          <Route key={path} path={path} element={<Suspense fallback={<Spinner/>}><Page/></Suspense>}/>)}
      </Route>
      <Route path="*" element={<Navigate to="/" replace/>}/>
    </Routes>
  </ToastProvider></ThemeProvider></AuthProvider></BrowserRouter></QueryClientProvider>;
}
