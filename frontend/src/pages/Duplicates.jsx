import { useCallback, useEffect, useState } from "react";
import { Copy, Fingerprint, GitCompare, Trash2 } from "lucide-react";
import { api } from "../services/api.js";
import { useScan } from "../context/scan.jsx";
import { useDrawer } from "../context/drawer.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, Notice, PageHeader, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
import { Checkbox } from "../components/ui/controls.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import { driveLinkActions } from "../components/details.js";
import { DriveFileLinks, DriveTrashNotice } from "../components/GoogleLinks.jsx";
import { useGoogleLinks } from "../hooks/useGoogleLinks.js";
import { formatBytes, formatDate, shortHash } from "../utils/format.js";

const LEVEL = {
  hash: { label: "Identical content · checksum match", tone: "ok", icon: Fingerprint },
  size_name: { label: "Same size + name · no checksum (Google Docs)", tone: "accent", icon: Copy },
  name: { label: "Versions · review needed", tone: "warn", icon: GitCompare },
};

export default function Duplicates() {
  const [groups, setGroups] = useState(null);
  const [keep, setKeep] = useState({});
  const [ack, setAck] = useState({});
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [removed, setRemoved] = useState(null); // copies moved to Drive's Trash this visit
  const { version } = useScan();
  const { open } = useDrawer();
  const toast = useToast();
  const links = useGoogleLinks();

  const load = useCallback(async () => {
    const data = await api.getDuplicates();
    setGroups(data);
    setKeep((prev) => {
      const next = { ...prev };
      for (const g of data) if (!(g.id in next)) next[g.id] = g.recommended_keep_drive_id;
      return next;
    });
  }, []);

  useEffect(() => {
    load().catch((e) => toast(e.message, "error"));
  }, [load, version, toast]);

  async function trash() {
    setBusy(true);
    try {
      const res = await api.trashDuplicates(confirm.id, keep[confirm.id], !!ack[confirm.id]);
      const ok = res.trashed.filter((r) => r.success);
      const failed = res.trashed.length - ok.length;
      toast(
        failed
          ? `Moved ${ok.length} file(s) to Trash; ${failed} couldn't be moved — see History.`
          : `Moved ${ok.length} file(s) to Drive's Trash — ${formatBytes(ok.reduce((s, r) => s + r.saved_bytes, 0))} freed once it's emptied.`,
        failed ? "error" : "success",
      );
      if (ok.length) {
        setRemoved((prev) => ({
          count: (prev?.count || 0) + ok.length,
          bytes: (prev?.bytes || 0) + ok.reduce((s, r) => s + r.saved_bytes, 0),
        }));
      }
      setConfirm(null);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  if (!groups) return <Card bodyClassName="p-0"><SkeletonRows rows={8} /></Card>;

  const copies = groups.filter((g) => !g.review_only);
  const recoverable = copies.reduce((s, g) => s + g.potential_recovery_bytes, 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Duplicates"
        description="Exact copies are matched by the SHA-256/MD5 checksum Google Drive stores for every file — not by name. Files that only share a name are listed last as versions to review."
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="Copy groups" value={copies.length} />
        <Stat label="Recoverable" value={formatBytes(recoverable)} tone="ok" sub="after Drive's Trash empties" />
        <Stat label="Version groups" value={groups.length - copies.length} sub="review only, not counted" className="col-span-2 lg:col-span-1" />
      </div>

      {removed && (
        <DriveTrashNotice>
          Moved <span className="mono">{removed.count}</span> cop{removed.count === 1 ? "y" : "ies"} to Drive&apos;s Trash.{" "}
          <span className="mono">{formatBytes(removed.bytes)}</span> still counts against your storage until the Trash is emptied — review
          there, then empty it to free the space now.
        </DriveTrashNotice>
      )}

      {groups.length === 0 ? (
        <Card><EmptyState icon={Copy} title="No duplicates found" subtitle="Run a scan after adding files." /></Card>
      ) : (
        groups.map((g) => {
          const level = LEVEL[g.match_level] || LEVEL.name;
          const keepId = keep[g.id];
          const removable = g.files.filter((f) => f.drive_id !== keepId);
          const removableBytes = removable.reduce((s, f) => s + f.size_bytes, 0);
          const blocked = g.review_only && !ack[g.id];
          return (
            <Card
              key={g.id}
              title={
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone={level.tone}><level.icon className="h-3 w-3" /> {level.label}</Badge>
                  <span className="mono text-[12px] font-normal text-faint">group {g.id} · {g.files.length} files</span>
                </span>
              }
              action={
                <span className="text-[12px] text-sub">
                  {g.review_only ? "Not counted" : <>Frees <span className="mono text-ok-ink">{formatBytes(removableBytes)}</span></>}
                </span>
              }
              bodyClassName="p-0"
            >
              {g.review_only && (
                <Notice tone="warn" className="m-3 mb-0">
                  Same name, different sizes — so different content. These look like versions of one document, not copies.
                  Compare them before removing any.
                </Notice>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead className="border-b border-line">
                    <tr>
                      <th className="th w-14">Keep</th><th className="th">Name</th><th className="th">Folder</th>
                      <th className="th text-right">Size</th><th className="th">Modified</th><th className="th">Checksum</th>
                      <th className="th w-16"><span className="sr-only">Links</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {g.files.map((f) => (
                      <tr
                        key={f.drive_id}
                        className={`cursor-pointer ${keepId === f.drive_id ? "bg-ok-soft/60" : "hover:bg-canvas"}`}
                        onClick={() =>
                          open({
                            kind: "Duplicate group member",
                            title: f.name,
                            subtitle: f.folder_path,
                            badges: [{ label: level.label, tone: level.tone }, ...(keepId === f.drive_id ? [{ label: "Kept", tone: "ok" }] : [])],
                            fields: [
                              { label: "MIME type", value: f.mime_type, mono: true },
                              { label: "Size", value: formatBytes(f.size_bytes), mono: true },
                              { label: "Checksum", value: f.content_hash || "—", mono: true },
                              { label: "Modified", value: formatDate(f.modified_time) },
                              { label: "Drive ID", value: f.drive_id, mono: true },
                            ],
                            actions: [
                              { label: "Keep this copy", variant: "primary", onClick: () => setKeep((p) => ({ ...p, [g.id]: f.drive_id })) },
                              ...driveLinkActions(f, links),
                            ],
                          })
                        }
                      >
                        <td className="td" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="radio"
                            name={`keep-${g.id}`}
                            checked={keepId === f.drive_id}
                            onChange={() => setKeep((p) => ({ ...p, [g.id]: f.drive_id }))}
                            className="accent-[rgb(var(--ok))]"
                            aria-label={`Keep ${f.name}`}
                          />
                        </td>
                        <td className="td max-w-[280px] truncate font-medium">{f.name}</td>
                        <td className="td max-w-[220px] truncate text-sub">{f.folder_path || "—"}</td>
                        <td className="td mono text-right">{formatBytes(f.size_bytes)}</td>
                        <td className="td whitespace-nowrap text-sub">{formatDate(f.modified_time)}</td>
                        <td className="td mono text-[12px] text-sub">{shortHash(f.content_hash)}</td>
                        <td className="td py-0 text-right"><DriveFileLinks file={f} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line px-4 py-2.5">
                {g.review_only && (
                  <label className="flex items-center gap-2 text-[12px] text-sub">
                    <Checkbox checked={ack[g.id]} onChange={(on) => setAck((p) => ({ ...p, [g.id]: on }))} label="I've compared them" />
                    I've compared them and don't need the others
                  </label>
                )}
                <Button variant="danger" size="sm" disabled={blocked} onClick={() => setConfirm(g)}>
                  <Trash2 className="h-3.5 w-3.5" /> Move {removable.length} to Trash
                </Button>
              </div>
            </Card>
          );
        })
      )}

      <ConfirmDialog
        open={!!confirm}
        danger
        title={confirm ? `Move ${confirm.files.filter((f) => f.drive_id !== keep[confirm.id]).length} file(s) to Drive's Trash?` : ""}
        description={confirm ? `Keeping “${confirm.files.find((f) => f.drive_id === keep[confirm.id])?.name}”.` : ""}
        consequences={[
          { kind: "undoable", text: "Restore any of them from History & Restore, or from Drive's Trash." },
          { kind: "permanent", text: "Google empties Drive's Trash after 30 days — the files are gone after that." },
          { kind: "info", text: "Space is only freed once the Trash is emptied." },
        ]}
        confirmLabel="Move to Trash"
        busy={busy}
        onConfirm={trash}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}
