import { useEffect, useState } from "react";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import { useUser } from "../hooks/useUser.jsx";
import Card from "../components/Card.jsx";
import { Loading } from "../components/Loading.jsx";

const INACTIVE_OPTIONS = [
  { value: 90, label: "90 days" }, { value: 180, label: "180 days" },
  { value: 365, label: "1 year" }, { value: 730, label: "2 years" },
];

export default function Settings() {
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState(null);
  const [savings, setSavings] = useState(null);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const { user } = useUser();

  useEffect(() => {
    Promise.all([api.getSettings(), api.getSavings()]).then(([s, sv]) => {
      setSettings(s);
      setSavings(sv);
      setLoading(false);
    });
  }, []);

  function set(field, value) {
    setSettings((prev) => ({ ...prev, [field]: value }));
  }

  async function save() {
    setSaving(true);
    try {
      const updated = await api.updateSettings(settings);
      setSettings(updated);
      toast("Settings saved.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Loading label="Loading settings…" />;

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500">Tune thresholds to match how you use your Drive — nothing here changes what's already on Drive.</p>
      </div>

      <Card title="Google Drive Connection">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-600">Connected account</span>
          <span className="font-medium text-slate-900">{user?.email}{user?.is_demo ? " (Demo Mode)" : ""}</span>
        </div>
      </Card>

      <Card title="Large File Thresholds" subtitle="Files at or above these sizes are flagged for review.">
        <div className="grid grid-cols-3 gap-4">
          <Field label="Large (MB)"><input type="number" min="1" value={settings.large_file_mb} onChange={(e) => set("large_file_mb", +e.target.value)} className="input" /></Field>
          <Field label="Very large (MB)"><input type="number" min="1" value={settings.very_large_file_mb} onChange={(e) => set("very_large_file_mb", +e.target.value)} className="input" /></Field>
          <Field label="Huge (MB)"><input type="number" min="1" value={settings.huge_file_mb} onChange={(e) => set("huge_file_mb", +e.target.value)} className="input" /></Field>
        </div>
      </Card>

      <Card title="Inactive File Threshold" subtitle={'Files older than this are surfaced as "potentially inactive" — never deleted automatically.'}>
        <div className="flex gap-2 flex-wrap">
          {INACTIVE_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => set("inactive_days", o.value)}
              className={`px-4 py-2 rounded-lg text-sm font-medium border ${settings.inactive_days === o.value ? "bg-brand-600 text-white border-brand-600" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </Card>

      <Card title="Compression Preferences">
        <Field label={`JPEG quality (${settings.jpeg_quality})`}>
          <input type="range" min="30" max="95" value={settings.jpeg_quality} onChange={(e) => set("jpeg_quality", +e.target.value)} className="w-full" />
        </Field>
        <Field label="Minimum saving to recommend compression (%)">
          <input type="number" min="1" max="90" value={settings.min_saving_percent} onChange={(e) => set("min_saving_percent", +e.target.value)} className="input" />
        </Field>
        <label className="flex items-center gap-2 text-sm text-slate-600 mt-2">
          <input type="checkbox" checked={settings.allow_format_conversion} onChange={(e) => set("allow_format_conversion", e.target.checked)} />
          Allow format conversion (e.g. PNG → WebP) when it saves meaningfully more space
        </label>
      </Card>

      <Card title="Storage Pricing Configuration" subtitle="Illustrative only — see disclaimer below.">
        {savings?.next_plan ? (
          <div className="text-sm text-slate-600 space-y-1">
            <p>Next plan: <strong>{savings.next_plan.name}</strong> — {savings.next_plan.storage_gb} GB for {savings.currency} {savings.next_plan.price_monthly}/mo</p>
            <p>Effective equivalent cost: <strong>{savings.currency} {savings.effective_cost_per_gb} / GB</strong> beyond the free tier</p>
            <p className="text-xs text-slate-400 mt-2">{savings.disclaimer}</p>
          </div>
        ) : <p className="text-sm text-slate-400">No paid plan configured.</p>}
        <p className="text-xs text-slate-400 mt-3">Pricing comes from <code>data/storage_plans.json</code> on the server and can be updated without code changes.</p>
      </Card>

      <div className="flex justify-end">
        <button onClick={save} disabled={saving} className="px-5 py-2.5 rounded-xl bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700 disabled:opacity-60">
          {saving ? "Saving…" : "Save Settings"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block text-sm mb-3">
      <span className="block text-xs font-medium text-slate-500 mb-1">{label}</span>
      {children}
    </label>
  );
}
