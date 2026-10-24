import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../services/api.js";

export const isActive = (job) => Boolean(job) && (job.status === "queued" || job.status === "running");

/**
 * Tracks background jobs under keys you choose ("analyze", a Drive file id…)
 * and polls the unfinished ones. onFinish(key, job) fires once per job when it
 * reaches done/failed — immediately if it was already finished when tracked
 * (Demo Mode runs jobs inline, so they come back done).
 */
export function useJobs(onFinish, intervalMs = 1500) {
  const [jobs, setJobs] = useState({});
  const onFinishRef = useRef(onFinish);
  onFinishRef.current = onFinish;
  const settled = useRef(new Set());

  const settle = useCallback((key, job) => {
    if (job && !isActive(job) && !settled.current.has(job.id)) {
      settled.current.add(job.id);
      onFinishRef.current?.(key, job);
    }
  }, []);

  const track = useCallback(
    (key, job) => {
      setJobs((prev) => ({ ...prev, [key]: job }));
      settle(key, job);
    },
    [settle],
  );

  useEffect(() => {
    const active = Object.entries(jobs).filter(([, job]) => isActive(job));
    if (!active.length) return undefined;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const updates = await Promise.all(
        // A failed poll (e.g. network blip) keeps the old state and retries next tick.
        active.map(([key, job]) => api.getJob(job.id).then((fresh) => [key, fresh], () => [key, job])),
      );
      if (cancelled) return;
      setJobs((prev) => {
        const next = { ...prev };
        for (const [key, job] of updates) if (next[key]?.id === job.id) next[key] = job;
        return next;
      });
      updates.forEach(([key, job]) => settle(key, job));
    }, intervalMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobs, intervalMs, settle]);

  return { jobs, track };
}
