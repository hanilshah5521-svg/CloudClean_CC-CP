import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Play, Plus, Trash2 } from "lucide-react";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import { isActive, useJobs } from "../hooks/useJobs.js";
import { Button } from "./ui/button.jsx";
import { Card } from "./ui/primitives.jsx";
import { Checkbox } from "./ui/controls.jsx";
import { ConfirmDialog } from "./ui/dialog.jsx";
import { JobStatus } from "./ui/progress.jsx";
import { cn } from "../lib/cn.js";
import { formatDateTime } from "../utils/format.js";

const CATEGORIES = [{ value: "video", label: "videos" }, { value: "images", label: "images" }, { value: "pdf", label: "PDFs" }];
const FIELDS = ["category", "min_size_mb", "min_inactive_days", "enabled", "auto_apply"];
const NEW_RULE = { category: "video", min_size_mb: 200, min_inactive_days: 90, enabled: true, auto_apply: false };

export default function RulesCard() {
  const [data, setData] = useState(null);
  const toast = useToast();

  const load = useCallback(async () => setData(await api.getRules()), []);
  const { jobs, track } = useJobs(async (_key, job) => {
    if (job.status === "done") toast(`Rules checked: ${job.result?.message || "done."}`);
    else toast(job.error || "Checking rules failed.", "error");
    await load();
  });

  useEffect(() => {
    load().catch((e) => toast(e.message, "error"));
  }, [load, toast]);

  if (!data) return null;
  const hour = new Date(Date.UTC(2020, 0, 1, data.schedule_hour_utc)).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  return (
    <Card
      title="Nightly auto-compression rules"
      subtitle={`Checked every night at ${hour}. Matches become suggestions on the Compression page; nothing is compressed unless a rule has auto-apply on.`}
      action={
        <div className="flex gap-2">
          <Button size="sm" onClick={() => api.createRule(NEW_RULE).then(load, (e) => toast(e.message, "error"))}><Plus className="h-3.5 w-3.5" /> Add rule</Button>
          <Button size="sm" variant="primary" disabled={!data.rules.length || isActive(jobs.rules)} onClick={() => api.runRules().then((j) => track("rules", j), (e) => toast(e.message, "error"))}>
            <Play className="h-3.5 w-3.5" /> {isActive(jobs.rules) ? "Checking…" : "Run now"}
          </Button>
        </div>
      }
    >
      <div className="space-y-2">
        {data.rules.length === 0 && <p className="text-[13px] text-faint">No rules yet. Example: compress videos larger than 200 MB not modified in 90 days.</p>}
        {data.rules.map((rule) => <RuleRow key={rule.id} rule={rule} maxAuto={data.max_auto_apply_per_run} onChanged={load} />)}
      </div>
      {isActive(jobs.rules) && <JobStatus job={jobs.rules} className="mt-3" />}
      <p className="mt-3 text-[11px] text-faint">
        {data.last_run_at ? <>Last checked <span className="mono">{formatDateTime(data.last_run_at)}</span> · </> : "Not checked yet · "}
        suggestions appear on the <Link to="/compression" className="text-accent-ink hover:underline">Compression page</Link>.
      </p>
    </Card>
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
