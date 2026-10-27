import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../services/api.js";
import { isActive, useJobs } from "../hooks/useJobs.js";
import { useToast } from "../hooks/useToast.jsx";

/**
 * One shared "Run Scan" for the whole app. It scans every linked Google
 * account — one background analysis job per account, each run with that
 * account's own token — and `job` sums them up for the progress bar.
 * `version` bumps when a scan finishes — screens reload on it.
 */
const ScanContext = createContext(null);
const keyOf = (accountId) => `analyze:${accountId}`;

export function ScanProvider({ children }) {
  const toast = useToast();
  const [starting, setStarting] = useState(false);
  const [version, setVersion] = useState(0);
  const run = useRef({ pending: new Set(), files: 0, failed: [], emails: {} });

  const { jobs, track } = useJobs((key, job) => {
    const r = run.current;
    if (!r.pending.has(key)) return;
    r.pending.delete(key);
    if (job.status === "done") r.files += job.result?.files_analyzed || 0;
    else r.failed.push(`${r.emails[key]}: ${job.error || "analysis failed"}`);
    if (r.pending.size) return;
    setVersion((v) => v + 1);
    const accounts = Object.keys(r.emails).length;
    if (r.failed.length) toast(`Scan finished with problems — ${r.failed.join("; ")}`, "error");
    else toast(accounts > 1 ? `Scanned ${accounts} accounts — ${r.files} files checked.` : `Analysis complete — ${r.files} files checked.`);
  });

  const follow = useCallback(
    (scans) => {
      run.current = { pending: new Set(scans.map((s) => keyOf(s.account_id))), files: 0, failed: [], emails: {} };
      for (const s of scans) run.current.emails[keyOf(s.account_id)] = s.email;
      for (const s of scans) track(keyOf(s.account_id), s.job);
    },
    [track],
  );

  useEffect(() => {
    // Pick up scans still running from before a page reload.
    api.activeAccountScans().then((scans) => scans.length && follow(scans), () => {});
  }, [follow]);

  const runDrive = useCallback(async () => {
    setStarting(true);
    try {
      follow(await api.scanAllAccounts());
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setStarting(false);
    }
  }, [follow, toast]);

  const job = useMemo(() => {
    const keys = Object.keys(run.current.emails);
    const current = keys.map((k) => jobs[k]).filter(Boolean);
    if (!current.length) return null;
    const running = current.filter(isActive);
    if (current.length === 1) return current[0];
    const progress = current.reduce((s, j) => s + (isActive(j) ? j.progress || 0 : 100), 0) / current.length;
    const now = running.find((j) => j.status === "running") || running[0];
    const nowKey = now && keys.find((k) => jobs[k] === now);
    return {
      status: running.length ? (running.some((j) => j.status === "running") ? "running" : "queued") : "done",
      progress,
      message: now
        ? `Scanning ${current.length - running.length + 1} of ${current.length} accounts — ${run.current.emails[nowKey]}: ${now.message || "starting…"}`
        : "Done",
      worker_online: current.every((j) => j.worker_online !== false),
    };
  }, [jobs]);

  const value = useMemo(
    () => ({
      job,
      scanning: starting || isActive(job),
      runDrive,
      version,
      refresh: () => setVersion((v) => v + 1),
    }),
    [job, starting, runDrive, version],
  );
  return <ScanContext.Provider value={value}>{children}</ScanContext.Provider>;
}

export function useScan() {
  const ctx = useContext(ScanContext);
  if (!ctx) throw new Error("useScan must be used within ScanProvider");
  return ctx;
}
