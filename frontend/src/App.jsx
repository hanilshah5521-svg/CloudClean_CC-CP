import { lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { UserProvider, useUser } from "./hooks/useUser.jsx";
import { ToastProvider } from "./hooks/useToast.jsx";
import { TooltipProvider } from "./components/ui/controls.jsx";
import { ThemeProvider } from "./context/theme.jsx";
import AppShell from "./components/shell/AppShell.jsx";
import Connect from "./pages/Connect.jsx";
// Each screen is its own chunk, so the first load doesn't pull in Recharts etc.
const Account = lazy(() => import("./pages/Account.jsx"));
const Dashboard = lazy(() => import("./pages/Dashboard.jsx"));
const FileExplorer = lazy(() => import("./pages/FileExplorer.jsx"));
const Duplicates = lazy(() => import("./pages/Duplicates.jsx"));
const Organize = lazy(() => import("./pages/Organize.jsx"));
const Compression = lazy(() => import("./pages/Compression.jsx"));
const Gmail = lazy(() => import("./pages/Gmail.jsx"));
const History = lazy(() => import("./pages/History.jsx"));
const Analytics = lazy(() => import("./pages/Analytics.jsx"));
const S3 = lazy(() => import("./pages/S3.jsx"));
const Settings = lazy(() => import("./pages/Settings.jsx"));

function Splash() {
  return <div className="flex h-screen items-center justify-center text-[13px] text-faint">Checking session…</div>;
}

function RequireAuth({ children }) {
  const { user, loading } = useUser();
  if (loading) return <Splash />;
  if (!user) return <Navigate to="/connect" replace />;
  return children;
}

/** Signed-out: the standalone connect screen. Signed-in: the in-app account page (keeping any ?error=). */
function ConnectGate() {
  const { user, loading } = useUser();
  const { search } = useLocation();
  if (loading) return <Splash />;
  return user ? <Navigate to={`/account${search}`} replace /> : <Connect />;
}

function Home() {
  const { user, loading } = useUser();
  if (loading) return <Splash />;
  return <Navigate to={user ? "/dashboard" : "/connect"} replace />;
}

export default function App() {
  return (
    <ThemeProvider>
      <UserProvider>
        <ToastProvider>
          <TooltipProvider>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/connect" element={<ConnectGate />} />
              <Route
                element={
                  <RequireAuth>
                    <AppShell />
                  </RequireAuth>
                }
              >
                <Route path="/account" element={<Account />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/files" element={<FileExplorer />} />
                <Route path="/duplicates" element={<Duplicates />} />
                <Route path="/organize" element={<Organize />} />
                <Route path="/compression" element={<Compression />} />
                <Route path="/gmail" element={<Gmail />} />
                <Route path="/history" element={<History />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/s3" element={<S3 />} />
                <Route path="/settings" element={<Settings />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </TooltipProvider>
        </ToastProvider>
      </UserProvider>
    </ThemeProvider>
  );
}
