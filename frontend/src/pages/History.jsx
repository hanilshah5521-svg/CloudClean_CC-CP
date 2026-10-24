import { useCallback, useEffect, useState } from "react";
import { ExternalLink, FolderOpen, History as HistoryIcon, RotateCcw, Trash2 } from "lucide-react";
import { api } from "../services/api.js";
import { useScan } from "../context/scan.jsx";
import { useDrawer } from "../context/drawer.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { isActive, useJobs } from "../hooks/useJobs.js";
import { useGoogleLinks } from "../hooks/useGoogleLinks.js";
import { DEMO_LINK_REASON } from "../components/details.js";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, PageHeader, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import { JobStatus } from "../components/ui/progress.jsx";
import { daysUntil, formatBytes, formatDate, formatDateTime } from "../utils/format.js";

const ACTION_LABEL = {
  compressed: "Compressed", trashed: "Moved to Trash", archived: "Archived", archive_created: "Archive created",
  gmail_trashed: "Email to Trash", restored: "Restored", organized: "Organized into folder",
};
const STATUS_TONE = { success: "ok", skipped: "neutral", failed: "bad", reverted: "warn", in_progress: "accent" };

/** Where to look at what an action touched. file_drive_id is a file, a ZIP,
 * a folder (organized) or a Gmail message, depending on the action. */
function historyLinks(h, links) {
  const link = (label, icon, href) => ({ label, icon, href, disabledReason: DEMO_LINK_REASON });
  const inTrash = h.status === "success";
  switch (h.action) {
    case "compressed":
    case "archive_created":
      return [link("Open in Drive", ExternalLink, links.fileById(h.file_drive_id))];
    case "organized":
      return [link("Open folder in Drive", FolderOpen, links.folder(h.file_drive_id))];
    case "trashed":
    case "archived":
      if (inTrash) return [link("Open Drive Trash", Trash2, links.driveTrash)];
      return h.status === "reverted" ? [link("Open in Drive", ExternalLink, links.fileById(h.file_drive_id))] : [];
    case "gmail_trashed":
      if (inTrash) return [link("Open Gmail Trash", Trash2, links.gmailTrash)];
      return h.status === "reverted" ? [link("Open in Gmail", ExternalLink, links.gmailMessageById(h.file_drive_id))] : [];
    default:
      return [];
  }
}

export default function History() {
  const [rows, setRows] = useState(null);
  const [freeing, setFreeing] = useState(null);
  const [busy, setBusy] = useState(null);
  const { version } = useScan();
  const { open } = useDrawer();
  const toast = useToast();
  const links = useGoogleLinks();

  const load = useCallback(async () => setRows(await api.getHistory()), []);

  // Undoing a video (or other large) compression is a background job.
  const { jobs, track } = useJobs(async (_key, job) => {
    if (job.status === "done") toast(job.result?.message || "Restored.");
    else toast(job.error || "Restore failed.", "error");
    await load();
  });

  useEffect(() => {
    load().catch((e) => toast(e.message, "error"));
    api.listJobs({ active: true, kind: "restore" }).then((list) => list.forEach((job) => track(job.payload.action_id, job)), () => {});
  }, [load, track, version, toast]);

  async function restore(h) {
    setBusy(h.id);
    try {
      const res = await api.restoreAction(h.id);
      if (res.job_id) track(h.id, res.job);
      else {
        toast(res.message || "Restored.");
        await load();
      }
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function freeSpace() {
    setBusy(freeing.id);
    try {
      toast((await api.freeSpace(freeing.id)).message);
      setFreeing(null);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  }

  if (!rows) return <Card bodyClassName="p-0"><SkeletonRows rows={10} cols={6} /></Card>;

  const recovered = rows.filter((h) => h.status === "success").reduce((s, h) => s + h.saved_bytes, 0);
  const pending = rows.filter((h) => h.can_free_space);
  const pendingBytes = pending.reduce((s, h) => s + h.original_size_bytes, 0);

  return (
    <div className="space-y-4">
      <PageHeader title="History & Restore" description="Every change CloudClean made, with what's needed to undo it." />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="Space recovered" value={formatBytes(recovered)} tone="ok" sub="from successful actions" />
        <Stat label="Originals kept for Undo" value={formatBytes(pendingBytes)} tone={pending.length ? "warn" : undefined} sub={`${pending.length} file(s) — still using storage`} />
        <Stat label="Actions" value={rows.length} className="col-span-2 lg:col-span-1" />
      </div>

      <Card bodyClassName="p-0">
        {rows.length === 0 ? (
          <EmptyState icon={HistoryIcon} title="No actions yet" subtitle="Compress, organize, archive or trash something to see it here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="border-b border-line">
                <tr>
                  <th className="th">File · action</th><th className="th text-right">Before → After</th>
                  <th className="th text-right">Saved</th><th className="th">Status</th>
                  <th className="th">Original kept</th><th className="th" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((h) => {
                  const job = jobs[h.id];
                  const left = daysUntil(h.original_delete_at);
                  return (
                    <tr
                      key={h.id}
                      className="cursor-pointer hover:bg-canvas"
                      onClick={() =>
                        open({
                          kind: ACTION_LABEL[h.action] || h.action,
                          title: h.file_name,
                          badges: [{ label: h.status.replace("_", " "), tone: STATUS_TONE[h.status] }],
                          fields: [
                            { label: "Before", value: formatBytes(h.original_size_bytes), mono: true },
                            { label: "After", value: formatBytes(h.new_size_bytes), mono: true },
                            { label: "Saved", value: formatBytes(h.saved_bytes), mono: true },
                            { label: "When", value: formatDateTime(h.created_at) },
                            ...(h.original_delete_at ? [{ label: "Original kept until", value: formatDate(h.original_delete_at) }] : []),
                          ],
                          reason: h.detail,
                          actions: historyLinks(h, links),
                        })
                      }
                    >
                      <td className="td max-w-[280px] py-2">
                        <div className="truncate font-medium">{h.file_name}</div>
                        <div className="text-[11px] text-faint">{ACTION_LABEL[h.action] || h.action} · {formatDate(h.created_at)}</div>
                      </td>
                      <td className="td mono text-right text-sub">{formatBytes(h.original_size_bytes)} → {formatBytes(h.new_size_bytes)}</td>
                      <td className="td mono text-right text-ok-ink">{h.saved_bytes ? formatBytes(h.saved_bytes) : <span className="text-faint">—</span>}</td>
                      <td className="td"><Badge tone={STATUS_TONE[h.status]}>{h.status.replace("_", " ")}</Badge></td>
                      <td className="td py-2">
                        {h.can_free_space && h.original_delete_at ? (
                          <div className="text-[12px] text-warn-ink">
                            <div>until {formatDate(h.original_delete_at)}</div>
                            <div className="mono text-[11px]">{left} days left</div>
                          </div>
                        ) : (
                          <span className="text-faint">—</span>
                        )}
                      </td>
                      <td className="td" onClick={(e) => e.stopPropagation()}>
                        {isActive(job) ? (
                          <div className="w-44"><JobStatus job={job} /></div>
                        ) : (
                          <div className="flex justify-end gap-1">
                            {h.restorable && (
                              <Button size="sm" disabled={busy === h.id} onClick={() => restore(h)}>
                                <RotateCcw className="h-3.5 w-3.5" /> {h.action === "compressed" || h.action === "organized" ? "Undo" : "Restore"}
                              </Button>
                            )}
                            {h.can_free_space && (
                              <Button variant="danger" size="sm" onClick={() => setFreeing(h)}>
                                <Trash2 className="h-3.5 w-3.5" /> Free space now
                              </Button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={!!freeing}
        danger
        title="Delete the original version now?"
        description={freeing ? `${freeing.file_name} — frees ${formatBytes(freeing.original_size_bytes)} immediately.` : ""}
        consequences={[
          { kind: "permanent", text: "The original, uncompressed version is deleted from Google Drive. This compression can no longer be undone." },
          { kind: "info", text: freeing?.original_delete_at ? `Otherwise CloudClean deletes it automatically on ${formatDate(freeing.original_delete_at)}.` : "The compressed file itself stays as it is." },
        ]}
        confirmLabel="Delete original"
        busy={busy === freeing?.id}
        onConfirm={freeSpace}
        onCancel={() => setFreeing(null)}
      />
    </div>
  );
}
