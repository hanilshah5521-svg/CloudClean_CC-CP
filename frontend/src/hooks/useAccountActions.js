import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api.js";
import { useUser } from "./useUser.jsx";
import { useToast } from "./useToast.jsx";

/**
 * Connect / demo / sign-out, shared by the top-right profile menu and the
 * Account section of Settings. `status` says whether Google sign-in is set up
 * on this server (null until loaded).
 */
export function useAccountActions() {
  const { user, refresh, logout } = useUser();
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();

  useEffect(() => {
    api.getAuthStatus().then(setStatus, () => setStatus({ google_configured: false }));
  }, []);

  const connectGoogle = useCallback(() => {
    window.location.href = api.googleLoginUrl;
  }, []);

  const startDemo = useCallback(async () => {
    setBusy(true);
    try {
      await api.demoLogin();
      await refresh();
      toast("Started a fresh Demo Mode session.");
      navigate("/dashboard");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }, [refresh, navigate, toast]);

  const signOut = useCallback(async () => {
    await logout();
    navigate("/connect");
  }, [logout, navigate]);

  return { user, status, busy, connectGoogle, startDemo, signOut };
}
