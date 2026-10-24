import { useState } from "react";
import { Archive, Clock, Copy, FileCode2, Image, Layers } from "lucide-react";
import { s3Api, CLASS_META, formatUsd } from "../../services/s3Api.js";
import { useDrawer } from "../../context/drawer.jsx";
import { Button } from "../ui/button.jsx";
import { Badge, Card, EmptyState, Legend, SegmentedBar, Stat } from "../ui/primitives.jsx";
import { Modal } from "../ui/dialog.jsx";
import { formatBytes } from "../../utils/format.js";

const TYPE_ICON = { tiering: Layers, noncurrent: Clock, abort_uploads: Archive, duplicates: Copy, compress: Image };
const RISK_TONE = { low: "ok", medium: "warn", high: "bad" };

export default function S3Overview({ data, onChanged, onOpenTab, toast }) {
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const { open } = useDrawer();

  async function openPreview(rec) {
    try {
      setPreview({ rec, ...(await s3Api.preview(rec.id)) });
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function apply() {
    setBusy(true);
    try {
      toast((await s3Api.apply(preview.rec.id)).message);
      setPreview(null);
      await onChanged();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  const classes = Object.entries(data.bytes_by_class || {}).sort((a, b) => b[1] - a[1]);
  const segments = classes.map(([cls, bytes]) => ({ key: cls, label: CLASS_META[cls]?.label || cls, value: bytes, color: CLASS_META[cls]?.color || "rgb(var(--faint))" }));
  const after = Math.max(0, data.monthly_cost_usd - data.potential_monthly_saving_usd);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Stored" value={formatBytes(data.total_bytes)} sub={`${data.buckets.length} buckets`} />
        <Stat label="Estimated cost" value={`${formatUsd(data.monthly_cost_usd)}/mo`} sub={`${data.pricing_region} list prices`} />
        <Stat label="After recommendations" value={`${formatUsd(after)}/mo`} tone="ok" sub={`${formatUsd(data.monthly_cost_usd)} → ${formatUsd(after)}`} />
        <Stat label="Potential saving" value={`${formatUsd(data.potential_monthly_saving_usd)}/mo`} tone="ok" sub={`${data.recommendations.length} recommendations`} />
      </div>

      <Card title="Storage classes" subtitle="Same bytes, very different prices — Deep Archive costs ~23× less than Standard.">
        <SegmentedBar segments={segments} height="h-3" />
        <div className="mt-3"><Legend items={segments} /></div>
      </Card>

      <Card title="Recommendations" subtitle="Lifecycle rules are previewed as JSON and merged into each bucket's existing rules." bodyClassName="p-0">
        {data.recommendations.length === 0 ? (
          <EmptyState title="Nothing to optimize" subtitle="Scan again after your data changes." />
        ) : (
          <ul className="divide-y divide-line">
            {data.recommendations.map((rec) => {
              const Icon = TYPE_ICON[rec.type] || Layers;
              return (
                <li key={rec.id} className="flex items-center gap-3 px-4 py-2.5">
                  <Icon className="h-4 w-4 shrink-0 text-sub" strokeWidth={1.75} />
                  <button
                    className="min-w-0 flex-1 text-left"
                    onClick={() =>
                      open({
                        kind: "S3 recommendation",
                        title: rec.title,
                        subtitle: rec.bucket,
                        badges: [{ label: `${rec.risk} risk`, tone: RISK_TONE[rec.risk] }, { label: `${Math.round(rec.confidence * 100)}% confidence`, tone: "neutral" }],
                        fields: [
                          { label: "Monthly saving", value: `${formatUsd(rec.monthly_saving_usd)}/mo`, mono: true },
                          { label: "One-time cost", value: formatUsd(rec.one_time_cost_usd), mono: true },
                          ...(rec.saving_bytes ? [{ label: "Bytes freed", value: formatBytes(rec.saving_bytes), mono: true }] : []),
                        ],
                        reason: rec.reason,
                      })
                    }
                  >
                    <div className="truncate text-[13px] font-medium text-ink">{rec.title}</div>
                    <div className="truncate text-[12px] text-faint">{rec.reason}</div>
                  </button>
                  <Badge tone={RISK_TONE[rec.risk]} className="hidden sm:inline-flex">{rec.risk}</Badge>
                  <span className="mono w-24 shrink-0 text-right text-[13px] text-ok-ink">{formatUsd(rec.monthly_saving_usd)}/mo</span>
                  {rec.action === "apply_lifecycle" ? (
                    <Button size="sm" onClick={() => openPreview(rec)}><FileCode2 className="h-3.5 w-3.5" /> Preview rule</Button>
                  ) : (
                    <Button size="sm" onClick={() => onOpenTab(rec.type === "duplicates" ? "duplicates" : "compression")}>Review</Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card title="Buckets" bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="border-b border-line">
              <tr>
                <th className="th">Bucket</th><th className="th">Region</th><th className="th text-right">Objects</th><th className="th text-right">Size</th>
                <th className="th text-right">Old versions</th><th className="th text-right">Unfinished uploads</th><th className="th text-right">Rules</th><th className="th text-right">Cost/mo</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.buckets.map((b) => (
                <tr key={b.id}>
                  <td className="td">
                    <span className="mono font-medium">{b.name}</span>
                    {b.versioning === "Enabled" && <Badge className="ml-2">versioned</Badge>}
                    {b.scan_error && <div className="text-[11px] text-bad-ink">{b.scan_error}</div>}
                    {b.truncated && <div className="text-[11px] text-warn-ink">Only the first 50,000 objects were scanned.</div>}
                  </td>
                  <td className="td mono text-sub">{b.region}</td>
                  <td className="td mono text-right">{b.object_count.toLocaleString()}</td>
                  <td className="td mono text-right">{formatBytes(b.total_bytes)}</td>
                  <td className="td mono text-right text-sub">{b.noncurrent_count ? `${b.noncurrent_count} · ${formatBytes(b.noncurrent_bytes)}` : "—"}</td>
                  <td className="td mono text-right text-sub">{b.incomplete_upload_count ? `${b.incomplete_upload_count} · ${formatBytes(b.incomplete_upload_bytes)}` : "—"}</td>
                  <td className="td mono text-right">{b.lifecycle_rule_count}</td>
                  <td className="td mono text-right font-medium">{formatUsd(b.monthly_cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t border-line px-4 py-2 text-[11px] text-faint">{data.pricing_disclaimer}</p>
      </Card>

      <Modal
        open={!!preview}
        onOpenChange={(o) => !o && !busy && setPreview(null)}
        wide
        title={preview ? `Add lifecycle rule to ${preview.bucket}?` : ""}
        description={
          preview
            ? `${preview.replaces_existing_rule ? "Replaces CloudClean's earlier rule with this ID. " : ""}The bucket's other ${preview.existing_rules.length} rule(s) stay unchanged. S3 applies lifecycle rules in a daily background pass. Undo removes the rule; objects it already moved stay in their new class.`
            : ""
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setPreview(null)} disabled={busy}>Cancel</Button>
            <Button variant="primary" onClick={apply} disabled={busy}>{busy ? "Applying…" : "Add rule"}</Button>
          </>
        }
      >
        {preview && <pre className="overflow-auto rounded border border-line bg-canvas p-3 text-[12px] leading-relaxed text-ink">{JSON.stringify(preview.rule, null, 2)}</pre>}
      </Modal>
    </div>
  );
}
