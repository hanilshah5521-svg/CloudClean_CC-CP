import { Navigate, Route, Routes } from "react-router-dom";
import { UserProvider, useUser } from "./hooks/useUser.jsx";
import { ToastProvider } from "./hooks/useToast.jsx";
import AppShell from "./layouts/AppShell.jsx";
import Landing from "./pages/Landing.jsx";
import Connect from "./pages/Connect.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import FileExplorer from "./pages/FileExplorer.jsx";
import Duplicates from "./pages/Duplicates.jsx";
import Compression from "./pages/Compression.jsx";
import Analytics from "./pages/Analytics.jsx";
import History from "./pages/History.jsx";
import Settings from "./pages/Settings.jsx";
import { Loading } from "./components/Loading.jsx";

function RequireAuth({ children }) {
  const { user, loading } = useUser();
  if (loading) return <Loading label="Checking session…" />;
  if (!user) return <Navigate to="/connect" replace />;
  return children;
}

export default function App() {
  return (
    <UserProvider>
      <ToastProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/connect" element={<Connect />} />
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/files" element={<FileExplorer />} />
            <Route path="/duplicates" element={<Duplicates />} />
            <Route path="/compression" element={<Compression />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/history" element={<History />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ToastProvider>
    </UserProvider>
  );
}
