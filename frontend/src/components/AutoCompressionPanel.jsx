import { useCallback, useEffect, useState } from "react";
import { ChevronDown, Moon, Play, Plus, Sparkles, Trash2 } from "lucide-react";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import { isActive, useJobs } from "../hooks/useJobs.js";
import { Button } from "./ui/button.jsx";
import { Badge } from "./ui/primitives.jsx";
import { Checkbox } from "./ui/controls.jsx";
import { ConfirmDialog } from "./ui/dialog.jsx";
import { JobStatus } from "./ui/progress.jsx";
import { cn } from "../lib/cn.js";
import { formatDateTime } from "../utils/format.js";

const CATEGORIES = [{ value: "video", label: "videos" }, { value: "images", label: "images" }, { value: "pdf", label: "PDFs" }];
const FIELDS = ["category", "min_size_mb", "min_inactive_days", "enabled", "auto_apply"];
const NEW_RULE = { category: "video", min_size_mb: 200, min_inactive_days: 90, enabled: true, auto_apply: false };
// One-click starting points (suggest-only: nothing is compressed until you say so).
const PRESETS = [
  { label: "Old videos", hint: "over 200 MB, untouched 90 days", rule: { category: "video", min_size_mb: 200, min_inactive_days: 90 } },
  { label: "Big photos", hint: "over 5 MB, untouched 180 days", rule: { category: "images", min_size_mb: 5, min_inactive_days: 180 } },
  { label: "Heavy PDFs", hint: "over 20 MB, untouched 1 year", rule: { category: "pdf", min_size_mb: 20, min_inactive_days: 365 } },
];
const describe = (r) =>
  `${CATEGORIES.find((c) => c.value === r.category)?.label || r.category} > ${r.min_size_mb} MB · ${r.min_inactive_days}+ days old`;

/**
 * Auto-compression "autopilot": rules checked every night. Matches become
 * suggestions (the Rule suggestions tab), or are compressed straight away
 * when a rule has auto-apply on. Rules belong to the account being worked in.
 */
export default function AutoCompressionPanel({ account, onChecked }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);
  const toast = useToast();

  const load = useCallback(async () => setData(await api.getRules()), []);
  const { jobs, track } = useJobs(async (_key, job) => {
    if (job.status === "done") toast(`Rules checked: ${job.result?.message || "done."}`);
    else toast(job.error || "Checking rules failed.", "error");
    await load();
    await onChecked?.();
  });

  useEffect(() => {
    load().catch((e) => toast(e.message, "error"));
  }, [load, toast]);

  if (!data) return null;
  const hour = new Date(Date.UTC(2020, 0, 1, data.schedule_hour_utc)).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const enabled = data.rules.filter((r) => r.enabled);
  const auto = enabled.filter((r) => r.auto_apply);
  const on = enabled.length > 0;
  const checking = isActive(jobs.rules);

  const add = (rule) =>
    api.createRule({ ...NEW_RULE, ...rule }).then(
      async () => {
        await load();
        setOpen(true);
        toast("Rule added — it's checked tonight, or press Run now.");
      },
      (e) => toast(e.message, "error"),
    );
  const runNow = () => api.runRules().then((j) => track("rules", j), (e) => toast(e.message, "error"));

  return (
    <section
      className={cn(
        "overflow-hidden rounded-lg border",
        on ? "border-accent/40 bg-gradient-to-br from-accent-soft via-surface to-surface" : "border-line bg-surface",
      )}
    >
      <div className="flex flex-wrap items-start gap-4 px-4 py-4">
        <div className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-lg", on ? "bg-accent text-white" : "bg-canvas text-sub")}>
          <Sparkles className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[15px] font-semibold text-ink">Auto-compression</h2>
            {on ? (
              <Badge tone="ok">On · {enabled.length} rule{enabled.length === 1 ? "" : "s"}</Badge>
            ) : (
              <Badge>Off</Badge>
            )}
            {auto.length > 0 && <Badge tone="warn">Auto-apply on {auto.length}</Badge>}
          </div>
          <p className="mt-1 max-w-2xl text-[12px] text-sub">
            <Moon className="mr-1 inline h-3.5 w-3.5 align-[-2px]" />
            Every night at <span className="mono">{hour}</span> CloudClean checks your Drive against these rules. Matches land in{" "}
            <span className="font-medium text-ink">Rule suggestions</span> below — or are compressed for you, if a rule has auto-apply on
            (at most <span className="mono">{data.max_auto_apply_per_run}</span> a night, each undoable).
            {account ? <> Rules apply to <span className="mono">{account}</span>, the account you're working in.</> : null}
          </p>
          {data.rules.length > 0 && !open && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {data.rules.map((r) => (
                <Badge key={r.id} tone={r.enabled ? (r.auto_apply ? "warn" : "accent") : "neutral"}>
                  {describe(r)}{r.auto_apply ? " · auto" : ""}{r.enabled ? "" : " · paused"}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {data.rules.length > 0 && (
            <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)}>
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} /> {open ? "Hide rules" : "Edit rules"}
            </Button>
          )}
          <Button size="sm" onClick={() => add({})}><Plus className="h-3.5 w-3.5" /> Add rule</Button>
          <Button size="sm" variant="primary" disabled={!enabled.length || checking} onClick={runNow}>
            <Play className="h-3.5 w-3.5" /> {checking ? "Checking…" : "Run now"}
          </Button>
        </div>
      </div>

      {data.rules.length === 0 && (
        <div className="border-t border-line bg-canvas/60 px-4 py-3">
          <div className="mb-2 text-[12px] text-sub">Start with one click (suggest-only — nothing is compressed until you choose):</div>
          <div className="grid gap-2 sm:grid-cols-3">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                onClick={() => add(p.rule)}
                className="rounded-lg border border-line bg-surface px-3 py-2.5 text-left transition-colors hover:border-accent/50 hover:bg-accent-soft"
              >
                <div className="flex items-center gap-1.5 text-[13px] font-medium text-ink"><Plus className="h-3.5 w-3.5 text-accent-ink" /> {p.label}</div>
                <div className="mt-0.5 text-[12px] text-sub">{p.hint}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {open && data.rules.length > 0 && (
        <div className="space-y-2 border-t border-line bg-canvas/60 px-4 py-3">
          {data.rules.map((rule) => <RuleRow key={rule.id} rule={rule} maxAuto={data.max_auto_apply_per_run} onChanged={load} />)}
        </div>
      )}

      {(checking || data.last_run_at) && (
        <div className="border-t border-line px-4 py-2 text-[11px] text-faint">
          {checking ? <JobStatus job={jobs.rules} /> : <>Last checked <span className="mono">{formatDateTime(data.last_run_at)}</span></>}
        </div>
      )}
    </section>
  );
}

function RuleRow({ rule, maxAuto, onChanged }) {
  const [draft, setDraft] = useState(rule);
  const [busy, setBusy] = useState(false);
  const [confirmAuto, setConfirmAuto] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const toast = useToast();
  const dirty = FIELDS.some((f) => draft[f] !== rule[f]);

  useEffect(() => setDraft(rule), [rule]);
  const set = (field, value) => setDraft((p) => ({ ...p, [field]: value }));

  async function run(fn, done) {
    setBusy(true);
    try {
      await fn();
      if (done) toast(done);
      await onChanged();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn("rounded border px-3 py-2.5", draft.enabled ? "border-line bg-surface" : "border-line bg-canvas")}>
      <div className="flex flex-wrap items-center gap-2 text-[13px] text-ink">
        <span>Compress</span>
        <select value={draft.category} onChange={(e) => set("category", e.target.value)} className="field w-auto">
          {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        <span>larger than</span>
        <input type="number" min="1" value={draft.min_size_mb} onChange={(e) => set("min_size_mb", +e.target.value)} className="field mono w-20" aria-label="Minimum size in MB" />
        <span>MB, not modified in</span>
        <input type="number" min="0" value={draft.min_inactive_days} onChange={(e) => set("min_inactive_days", +e.target.value)} className="field mono w-20" aria-label="Minimum days since modified" />
        <span>days</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-4 text-[12px] text-sub">
        <label className="flex items-center gap-1.5"><Checkbox checked={draft.enabled} onChange={(v) => set("enabled", v)} label="Enabled" /> Enabled</label>
        <label className="flex items-center gap-1.5">
          <Checkbox checked={draft.auto_apply} onChange={(v) => (v ? setConfirmAuto(true) : set("auto_apply", false))} label="Auto-apply" /> Auto-apply
        </label>
        <div className="ml-auto flex gap-1">
          <Button variant="danger" size="sm" disabled={busy} onClick={() => setConfirmDelete(true)}><Trash2 className="h-3.5 w-3.5" /> Delete</Button>
          <Button variant="primary" size="sm" disabled={busy || !dirty} onClick={() => run(() => api.updateRule(rule.id, Object.fromEntries(FIELDS.map((f) => [f, draft[f]]))), "Rule saved.")}>Save</Button>
        </div>
      </div>
      {draft.auto_apply && (
        <p className="mt-2 text-[11px] text-warn-ink">Auto-apply: matching files are compressed without asking — at most <span className="mono">{maxAuto}</span> per night. Each stays undoable from History.</p>
      )}
      <ConfirmDialog
        open={confirmAuto}
        title="Turn on auto-apply?"
        consequences={[
          { kind: "info", text: `Every night, matching files are re-encoded and replaced on Drive without asking — at most ${maxAuto} per night.` },
          { kind: "undoable", text: "Each file is re-checked right before it's touched, and each compression can be undone from History." },
        ]}
        confirmLabel="Turn on auto-apply"
        onConfirm={() => {
          set("auto_apply", true);
          setConfirmAuto(false);
        }}
        onCancel={() => setConfirmAuto(false)}
      />
      <ConfirmDialog
        open={confirmDelete}
        danger
        title="Delete this rule?"
        consequences={[{ kind: "info", text: "Only the rule is removed. Files and existing suggestions aren't affected." }]}
        confirmLabel="Delete rule"
        busy={busy}
        onConfirm={() => run(() => api.deleteRule(rule.id)).then(() => setConfirmDelete(false))}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
