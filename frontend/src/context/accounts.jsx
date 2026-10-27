import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "../services/api.js";
import { useScan } from "./scan.jsx";
import { useToast } from "../hooks/useToast.jsx";

/**
 * The Google accounts linked into this profile. The session works in one of
 * them (`active`); switching reloads the app so every screen shows that
 * account's data and nothing from the previous one lingers.
 */
const AccountsContext = createContext(null);

export function AccountsProvider({ children }) {
  const { version } = useScan();
  const toast = useToast();
  const [summary, setSummary] = useState(null);
  const [adding, setAdding] = useState(false);

  const refresh = useCallback(() => api.getAccounts().then(setSummary, () => setSummary(null)), []);

  useEffect(() => {
    refresh();
  }, [refresh, version]);

  const switchTo = useCallback(
    async (id) => {
      try {
        await api.switchAccount(id);
        window.location.reload();
      } catch (e) {
        toast(e.message, "error");
      }
    },
    [toast],
  );

  const remove = useCallback(
    async (id) => {
      const res = await api.removeAccount(id);
      toast(`Removed ${res.removed} from this profile.`);
      await refresh();
    },
    [refresh, toast],
  );

  /** Google: sign in to another account (full-page redirect). Demo: add a simulated one. */
  const addAccount = useCallback(async () => {
    if (summary?.add_kind === "google") {
      window.location.href = api.googleLinkUrl;
      return;
    }
    setAdding(true);
    try {
      const res = await api.addSimulatedAccount();
      toast(`Linked ${res.email} and scanned it.`);
      await refresh();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setAdding(false);
    }
  }, [summary, refresh, toast]);

  const value = useMemo(() => {
    const accounts = summary?.accounts || [];
    return {
      summary,
      accounts,
      active: accounts.find((a) => a.active) || null,
      multiple: accounts.length > 1,
      refresh,
      switchTo,
      remove,
      addAccount,
      adding,
    };
  }, [summary, refresh, switchTo, remove, addAccount, adding]);
  return <AccountsContext.Provider value={value}>{children}</AccountsContext.Provider>;
}

export function useAccounts() {
  const ctx = useContext(AccountsContext);
  if (!ctx) throw new Error("useAccounts must be used within AccountsProvider");
  return ctx;
}

/** Stable colour per account, for the chips on files from different accounts. */
const ACCOUNT_TONES = ["accent", "ok", "warn", "info"];
export const accountTone = (accounts, id) => ACCOUNT_TONES[Math.max(0, accounts.findIndex((a) => a.id === id)) % ACCOUNT_TONES.length];
