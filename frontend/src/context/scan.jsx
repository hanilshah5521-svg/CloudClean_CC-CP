import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "../services/api.js";
import { s3Api } from "../services/s3Api.js";
import { isActive, useJobs } from "../hooks/useJobs.js";
import { useToast } from "../hooks/useToast.jsx";

/**
 * One shared "Run Scan" for the whole app. A Drive analysis runs as a
 * background job (progress polled here); an S3 scan is a single request.
 * `version` / `s3Version` bump when a scan finishes — screens reload on it.
 */
const ScanContext = createContext(null);

export function ScanProvider({ children }) {
  const toast = useToast();
  const [starting, setStarting] = useState(false);
  const [version, setVersion] = useState(0);
  const [s3Scanning, setS3Scanning] = useState(false);
  const [s3Version, setS3Version] = useState(0);

  const { jobs, track } = useJobs((_key, job) => {
    if (job.status === "done") {
      setVersion((v) => v + 1);
      toast(`Analysis complete — ${job.result?.files_analyzed ?? "all"} files checked.`);
    } else {
      toast(job.error || "Analysis failed.", "error");
    }
  });

  useEffect(() => {
    // Pick up an analysis still running from before a page reload.
    api.listJobs({ active: true, kind: "analyze", limit: 1 }).then(([job]) => job && track("analyze", job), () => {});
  }, [track]);

  const runDrive = useCallback(async () => {
    setStarting(true);
    try {
      track("analyze", await api.analyze());
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setStarting(false);
    }
  }, [track, toast]);

  const runS3 = useCallback(async () => {
    setS3Scanning(true);
    try {
      await s3Api.scan();
      setS3Version((v) => v + 1);
      toast("S3 scan complete.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setS3Scanning(false);
    }
  }, [toast]);

  const job = jobs.analyze;
  const value = useMemo(
    () => ({
      job,
      scanning: starting || isActive(job),
      runDrive,
      version,
      refresh: () => setVersion((v) => v + 1),
      s3Scanning,
      runS3,
      s3Version,
    }),
    [job, starting, runDrive, version, s3Scanning, runS3, s3Version],
  );
  return <ScanContext.Provider value={value}>{children}</ScanContext.Provider>;
}

export function useScan() {
  const ctx = useContext(ScanContext);
  if (!ctx) throw new Error("useScan must be used within ScanProvider");
  return ctx;
}
