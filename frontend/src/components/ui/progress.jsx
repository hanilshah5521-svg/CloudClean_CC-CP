import { Check } from "lucide-react";
import { cn } from "../../lib/cn.js";

/** Thin striped progress bar. */
export function StripedBar({ percent = 0, tone = "accent", active = true, className }) {
  const color = { accent: "bg-accent", ok: "bg-ok", bad: "bg-bad", warn: "bg-warn" }[tone];
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-sm bg-track", className)}>
      <div
        className={cn("h-full rounded-sm transition-[width] duration-500", color, active && "stripes")}
        style={{ width: `${Math.max(2, Math.min(100, percent))}%` }}
      />
    </div>
  );
}

/** Live status of a background job (see hooks/useJobs.js). */
export function JobStatus({ job, className }) {
  if (!job) return null;
  const queued = job.status === "queued";
  const failed = job.status === "failed";
  const percent = job.status === "done" ? 100 : job.progress || 0;
  const text = failed ? job.error : queued ? "Queued — waiting for the background worker…" : job.message || "Working…";
  return (
    <div className={cn("space-y-1", className)} role="status" aria-live="polite">
      <div className="flex justify-between gap-3 text-[12px]">
        <span className={cn("mono truncate", failed ? "text-bad-ink" : "text-sub")}>{text}</span>
        {!failed && <span className="mono shrink-0 text-faint">{Math.round(percent)}%</span>}
      </div>
      <StripedBar percent={queued ? 3 : percent} tone={failed ? "bad" : "accent"} active={!failed} />
      {queued && job.worker_online === false && (
        <p className="text-[11px] text-warn-ink">
          No background worker is running. Start it with <code>python -m app.worker</code> in <code>backend/</code>.
        </p>
      )}
    </div>
  );
}

const STAGES = ["Downloading", "Re-encoding", "Checking", "Uploading"];

/** Which stage a video job is in, from the worker's progress message. */
export function videoStage(job) {
  if (!job) return -1;
  if (job.status === "done") return STAGES.length;
  const msg = (job.message || "").toLowerCase();
  if (msg.startsWith("uploading")) return 3;
  if (msg.startsWith("checking")) return 2;
  if (msg.startsWith("re-encoding")) return 1;
  if (msg.startsWith("downloading")) return 0;
  return -1;
}

export function StagePills({ job }) {
  const current = videoStage(job);
  return (
    <div className="flex flex-wrap items-center gap-1">
      {STAGES.map((s, i) => {
        const done = i < current;
        const now = i === current;
        return (
          <span
            key={s}
            className={cn(
              "inline-flex items-center gap-1 rounded border px-1.5 py-px text-[11px]",
              done && "border-ok/25 bg-ok-soft text-ok-ink",
              now && "border-accent/30 bg-accent-soft font-medium text-accent-ink",
              !done && !now && "border-line bg-surface text-faint",
            )}
          >
            {done && <Check className="h-3 w-3" strokeWidth={2.5} />}
            {s}
          </span>
        );
      })}
    </div>
  );
}
