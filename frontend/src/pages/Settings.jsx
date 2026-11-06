import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import { Button } from "../components/ui/button.jsx";
import { Card, FilterPills, PageHeader, SkeletonRows } from "../components/ui/primitives.jsx";
import { Field, Slider } from "../components/ui/controls.jsx";
import AccountCard from "../components/AccountCard.jsx";

const INACTIVE = [{ value: 90, label: "90 days" }, { value: 180, label: "180 days" }, { value: 365, label: "1 year" }, { value: 730, label: "2 years" }];

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [saved, setSaved] = useState(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api.getSettings().then(
      (s) => {
        setSettings(s);
        setSaved(s);
      },
      (e) => toast(e.message, "error"),
    );
  }, [toast]);

  const set = (field, value) => setSettings((p) => ({ ...p, [field]: value }));
  const dirty = settings && saved && JSON.stringify(settings) !== JSON.stringify(saved);

  async function save() {
    setBusy(true);
    try {
      const { allow_format_conversion: _unused, ...body } = settings;
      const updated = await api.updateSettings(body);
      setSettings(updated);
      setSaved(updated);
      toast("Settings saved. They apply from the next scan.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  if (!settings) return <Card bodyClassName="p-0"><SkeletonRows rows={6} /></Card>;

  const num = (field, props = {}) => (
    <input type="number" className="field mono" value={settings[field]} onChange={(e) => set(field, +e.target.value)} {...props} />
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Settings"
        description="Your account, and the thresholds used by the next scan. Nothing here changes files already on Drive."
        actions={<Button variant="primary" disabled={!dirty || busy} onClick={save}><Save className="h-3.5 w-3.5" /> {busy ? "Saving…" : "Save settings"}</Button>}
      />

      <AccountCard />

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Large-file thresholds" subtitle="Files at or above these sizes are flagged for review (MB).">
          <div className="grid grid-cols-3 gap-3">
            <Field label="Large">{num("large_file_mb", { min: 1 })}</Field>
            <Field label="Very large">{num("very_large_file_mb", { min: 1 })}</Field>
            <Field label="Huge">{num("huge_file_mb", { min: 1 })}</Field>
          </div>
        </Card>

        <Card title="Inactivity" subtitle={'Files not modified for this long count as "potentially inactive" — never deleted automatically.'}>
          <FilterPills options={INACTIVE} value={settings.inactive_days} onChange={(v) => set("inactive_days", v)} />
        </Card>

        <Card title="Compression" subtitle="JPEG quality applies to images; the minimum saving to images, PDFs and videos. Nightly auto-compression rules are on the Compression page.">
          <Field label="JPEG quality" hint="Lower = smaller files, more visible artifacts. 70–80 is a good balance.">
            <div className="flex items-center gap-3">
              <Slider value={settings.jpeg_quality} onChange={(v) => set("jpeg_quality", v)} min={30} max={95} label="JPEG quality" />
              <span className="mono w-8 text-right text-[13px] text-ink">{settings.jpeg_quality}</span>
            </div>
          </Field>
          <Field
            label="Minimum saving to compress (% of the file's size)"
            hint="E.g. 10% means a 100 MB file must shrink by at least 10 MB. Files estimated to save less aren't suggested, and if the measured saving is smaller, nothing is uploaded."
            className="mt-4"
          >
            {num("min_saving_percent", { min: 1, max: 90 })}
          </Field>
        </Card>
      </div>


    </div>
  );
}
