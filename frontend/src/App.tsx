import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "@/components/Layout";
import { ToastProvider } from "@/components/Toast";
import { Spinner } from "@/components/ui";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { ThemeProvider } from "@/hooks/useTheme";
import { BASENAME, PODCASTS } from "@/lib/mode";
import Login from "@/pages/Login";
import { Privacy, Terms } from "@/pages/Legal";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Channels = lazy(() => import("@/pages/Channels"));
const ReviewQueue = lazy(() => import("@/pages/ReviewQueue"));
const Published = lazy(() => import("@/pages/Published"));
const Skipped = lazy(() => import("@/pages/Skipped"));
const NotProcessed = lazy(() => import("@/pages/NotProcessed"));
const Accounts = lazy(() => import("@/pages/Accounts"));
const MyIntegrations = lazy(() => import("@/pages/MyIntegrations"));
const Integrations = lazy(() => import("@/pages/Integrations"));
const EditingRules = lazy(() => import("@/pages/EditingRules"));
const LiveStatus = lazy(() => import("@/pages/LiveStatus"));
const ClipRules = lazy(() => import("@/pages/ClipRules"));
const DailyReport = lazy(() => import("@/pages/DailyReport"));
const BufferSettings = lazy(() => import("@/pages/BufferSettings"));
const PromptStudio = lazy(() => import("@/pages/PromptStudio"));
const Logs = lazy(() => import("@/pages/Logs"));
const Settings = lazy(() => import("@/pages/Settings"));
const PCHelper = lazy(() => import("@/pages/PCHelper"));

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

type Pages = readonly (readonly [string, React.ComponentType])[];
const SHORTS_PAGES: Pages = [["/", Dashboard], ["/status", LiveStatus], ["/channels", Channels], ["/review", ReviewQueue], ["/published", Published], ["/skipped", Skipped], ["/not-processed", NotProcessed], ["/editing", EditingRules], ["/integrations", Integrations], ["/report", DailyReport], ["/buffer", BufferSettings], ["/prompts", PromptStudio], ["/logs", Logs], ["/accounts", Accounts], ["/my-integrations", MyIntegrations], ["/helper", PCHelper], ["/settings", Settings]];
// The Podcasts window: the same screens, showing the Podcasts workspace's own channels, accounts, rules and reports.
const PODCAST_PAGES: Pages = [["/", Dashboard], ["/status", LiveStatus], ["/channels", Channels], ["/review", ReviewQueue], ["/published", Published], ["/skipped", Skipped], ["/not-processed", NotProcessed], ["/rules", ClipRules], ["/editing", EditingRules], ["/buffer", BufferSettings], ["/report", DailyReport]];

export default function App() {
  return <QueryClientProvider client={queryClient}><BrowserRouter basename={BASENAME}><AuthProvider><ThemeProvider><ToastProvider>
    <Routes>
      <Route path="/login" element={<Login/>}/>
      <Route path="/terms" element={<Terms/>}/>
      <Route path="/privacy" element={<Privacy/>}/>
      <Route element={<RequireAuth><Layout/></RequireAuth>}>
        {(PODCASTS ? PODCAST_PAGES : SHORTS_PAGES).map(([path, Page]) =>
          <Route key={path} path={path} element={<Suspense fallback={<Spinner/>}><Page/></Suspense>}/>)}
      </Route>
      <Route path="*" element={<Navigate to="/" replace/>}/>
    </Routes>
  </ToastProvider></ThemeProvider></AuthProvider></BrowserRouter></QueryClientProvider>;
}
