import { useEffect, useState } from "react";
import { Copy, Image, RotateCcw, Trash2 } from "lucide-react";
import { s3Api, CLASS_META, formatUsd } from "../../services/s3Api.js";
import { Button } from "../ui/button.jsx";
import { Badge, Card, EmptyState, SkeletonRows } from "../ui/primitives.jsx";
import { ConfirmDialog } from "../ui/dialog.jsx";
import { formatBytes, formatDate } from "../../utils/format.js";

function useLoad(fn, toast, deps = []) {
  const [data, setData] = useState(null);
  async function reload() {
    try {
      setData(await fn());
    } catch (e) {
      toast(e.message, "error");
      setData([]);
    }
  }
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return [data, reload];
}

export function S3Duplicates({ toast, onChanged, version }) {
  const [groups, reload] = useLoad(s3Api.duplicates, toast, [version]);
  const [keep, setKeep] = useState({});
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!groups) return <Card bodyClassName="p-0"><SkeletonRows /></Card>;
  if (!groups.length) return <Card><EmptyState icon={Copy} title="No duplicate objects" subtitle="No two objects in a bucket share the same ETag and size." /></Card>;

  const keyOf = (g) => `${g.bucket_id}:${g.group}`;
  const keepId = (g) => keep[keyOf(g)] ?? g.recommended_keep_id;

  async function remove() {
    setBusy(true);
    try {
      const { results } = await s3Api.trashDuplicates(confirm.bucket_id, confirm.group, keepId(confirm));
      const failed = results.filter((r) => !r.success);
      toast(failed.length ? `${failed.length} cop(ies) couldn't be removed: ${failed[0].message}` : `Removed ${results.length} cop(ies).`, failed.length ? "error" : "success");
      setConfirm(null);
      await reload();
      await onChanged();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <Card
          key={keyOf(g)}
          title={<span className="flex flex-wrap items-center gap-2"><Badge tone="ok">Identical · ETag + size</Badge><span className="mono text-[12px] font-normal text-faint">{g.bucket}</span></span>}
          action={<span className="text-[12px] text-sub">Frees <span className="mono text-ok-ink">{formatBytes(g.removable_bytes)}</span> · <span className="mono">{formatUsd(g.monthly_saving_usd)}/mo</span></span>}
          bodyClassName="p-0"
        >
          <table className="w-full text-[13px]">
            <thead className="border-b border-line">
              <tr><th className="th w-14">Keep</th><th className="th">Key</th><th className="th">Class</th><th className="th text-right">Size</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {g.objects.map((o) => (
                <tr key={o.id} className={keepId(g) === o.id ? "bg-ok-soft/60" : ""}>
                  <td className="td"><input type="radio" name={`keep-${keyOf(g)}`} checked={keepId(g) === o.id} onChange={() => setKeep((p) => ({ ...p, [keyOf(g)]: o.id }))} className="accent-[rgb(var(--ok))]" aria-label={`Keep ${o.key}`} /></td>
                  <td className="td mono max-w-[420px] truncate text-[12px]" title={o.key}>{o.key}</td>
                  <td className="td text-sub">{CLASS_META[o.storage_class]?.label || o.storage_class}</td>
                  <td className="td mono text-right">{formatBytes(o.size_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex justify-end border-t border-line px-4 py-2.5">
            <Button variant="danger" size="sm" onClick={() => setConfirm(g)}><Trash2 className="h-3.5 w-3.5" /> Remove {g.objects.length - 1} cop{g.objects.length - 1 === 1 ? "y" : "ies"}</Button>
          </div>
        </Card>
      ))}
      <ConfirmDialog
        open={!!confirm}
        danger
        title="Remove duplicate copies?"
        consequences={
          confirm?.versioned
            ? [
                { kind: "undoable", text: "Versioned bucket: each copy gets a delete marker; its data stays as a noncurrent version. Undo from S3 History removes the marker." },
                { kind: "info", text: "Check no application or link still uses these keys." },
              ]
            : [
                { kind: "undoable", text: "Each copy moves to the cloudclean-trash/ prefix — restore it from S3 History." },
                { kind: "permanent", text: "A lifecycle rule deletes cloudclean-trash/ objects after 30 days." },
                { kind: "info", text: "Check no application or link still uses these keys." },
              ]
        }
        confirmLabel="Remove copies"
        busy={busy}
        onConfirm={remove}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

export function S3Compression({ toast, onChanged, version }) {
  const [items, reload] = useLoad(s3Api.compression, toast, [version]);
  const [working, setWorking] = useState(null);

  if (!items) return <Card bodyClassName="p-0"><SkeletonRows /></Card>;
  if (!items.length) return <Card><EmptyState icon={Image} title="No compression candidates" subtitle="No JPEG/PNG/WebP/PDF objects over 1 MB look compressible." /></Card>;

  async function compress(id) {
    setWorking(id);
    try {
      const res = await s3Api.compress(id);
      toast(res.message, res.success ? "success" : "error");
      await reload();
      await onChanged();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setWorking(null);
    }
  }

  return (
    <Card subtitle="Re-encoded in the same format under the same key. The original is kept (noncurrent version, or a 30-day copy under cloudclean-trash/) so it can be restored." bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead className="border-b border-line">
            <tr><th className="th">Object</th><th className="th">Class</th><th className="th text-right">Size</th><th className="th text-right">Est. saving</th><th className="th" /></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((o) => (
              <tr key={o.id}>
                <td className="td mono max-w-[420px] truncate text-[12px]" title={`${o.bucket}/${o.key}`}><span className="text-faint">{o.bucket}/</span>{o.key}</td>
                <td className="td text-sub">{CLASS_META[o.storage_class]?.label || o.storage_class}</td>
                <td className="td mono text-right">{formatBytes(o.size_bytes)}</td>
                <td className="td mono text-right text-ok-ink">{formatBytes(o.estimated_saving_bytes)}</td>
                <td className="td text-right">
                  <Button variant="primary" size="sm" disabled={working !== null} onClick={() => compress(o.id)}>{working === o.id ? "Compressing…" : "Compress"}</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

const ACTION_LABEL = { lifecycle_rule_added: "Lifecycle rule added", trashed: "Copy removed", compressed: "Compressed", undone: "Undone" };
const STATUS_TONE = { success: "ok", skipped: "neutral", failed: "bad", reverted: "warn" };

export function S3History({ toast, onChanged, version }) {
  const [rows, reload] = useLoad(s3Api.history, toast, [version]);
  const [working, setWorking] = useState(null);

  if (!rows) return <Card bodyClassName="p-0"><SkeletonRows /></Card>;
  if (!rows.length) return <Card><EmptyState title="No S3 changes yet" subtitle="Applied rules, removed copies and compressions appear here." /></Card>;

  async function undo(id) {
    setWorking(id);
    try {
      toast((await s3Api.undo(id)).message);
      await reload();
      await onChanged();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setWorking(null);
    }
  }

  return (
    <Card bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead className="border-b border-line">
            <tr><th className="th">Change</th><th className="th">Bucket · target</th><th className="th text-right">Saving</th><th className="th">Status</th><th className="th">When</th><th className="th" /></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((h) => (
              <tr key={h.id} className="align-top">
                <td className="td whitespace-nowrap py-2" title={h.detail}>{ACTION_LABEL[h.action] || h.action}</td>
                <td className="td max-w-[380px] py-2">
                  <div className="mono truncate text-[12px]" title={h.target}>{h.bucket} · {h.target}</div>
                  <div className="line-clamp-2 whitespace-normal text-[11px] text-faint">{h.detail}</div>
                </td>
                <td className="td mono py-2 text-right text-ok-ink">{h.monthly_saving_usd ? `${formatUsd(h.monthly_saving_usd)}/mo` : "—"}</td>
                <td className="td py-2"><Badge tone={STATUS_TONE[h.status]}>{h.status}</Badge></td>
                <td className="td whitespace-nowrap py-2 text-faint">{formatDate(h.created_at)}</td>
                <td className="td py-2 text-right">
                  {h.restorable && (
                    <Button size="sm" disabled={working !== null} onClick={() => undo(h.id)}><RotateCcw className="h-3.5 w-3.5" /> {working === h.id ? "Undoing…" : "Undo"}</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
