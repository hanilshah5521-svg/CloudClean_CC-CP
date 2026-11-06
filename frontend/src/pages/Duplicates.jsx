import { useCallback, useEffect, useState } from "react";
import { Copy, Fingerprint, GitCompare, Trash2, Users } from "lucide-react";
import { api } from "../services/api.js";
import { accountTone, useAccounts } from "../context/accounts.jsx";
import { useScan } from "../context/scan.jsx";
import { useDrawer } from "../context/drawer.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, FilterPills, Notice, PageHeader, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
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
  cross: { label: "Identical copies in several accounts", tone: "info", icon: Users },
};

const short = (email) => email.split("@")[0];
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/**
 * Duplicate groups across every linked account. Each file shows the account
 * it's in; a group whose copies sit in two or more accounts is one
 * "cross-account" group, however many copies it has. Removing copies moves
 * them to the Trash of the account each one is in.
 */
export default function Duplicates() {
  const [groups, setGroups] = useState(null);
  const [keep, setKeep] = useState({}); // group id -> DriveFile id to keep
  const [ack, setAck] = useState({});
  const [filter, setFilter] = useState("");
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [removed, setRemoved] = useState(null); // copies moved to Drive's Trash this visit
  const { version } = useScan();
  const { accounts, active, multiple } = useAccounts();
  const { open } = useDrawer();
  const toast = useToast();
  const links = useGoogleLinks();

  const load = useCallback(async () => {
    const data = await api.getDuplicates();
    setGroups(data);
    setKeep((prev) => {
      const next = { ...prev };
      for (const g of data) if (!(g.id in next)) next[g.id] = g.recommended_keep_file_id;
      return next;
    });
  }, []);

  useEffect(() => {
    load().catch((e) => toast(e.message, "error"));
  }, [load, version, toast]);

  async function trash() {
    const g = confirm;
    const keepFile = g.files.find((f) => f.id === keep[g.id]);
    setBusy(true);
    try {
      let results;
      if (g.kind === "cross_account") {
        ({ results } = await api.removeCrossCopies(keepFile.id, g.files.filter((f) => f.id !== keepFile.id).map((f) => f.id)));
      } else {
        results = (await api.trashDuplicates(g.id, keepFile.drive_id, !!ack[g.id])).trashed;
      }
      const ok = results.filter((r) => r.success);
      const failed = results.length - ok.length;
      const freed = ok.reduce((s, r) => s + r.saved_bytes, 0);
      const where = otherAccountsNote(g);
      toast(
        failed
          ? `Moved ${ok.length} file(s) to Trash; ${failed} couldn't be moved — see History${where}.`
          : `Moved ${ok.length} file(s) to Drive's Trash — ${formatBytes(freed)} freed once it's emptied.${where ? ` Recorded in History${where}.` : ""}`,
        failed ? "error" : "success",
      );
      if (ok.length) setRemoved((prev) => ({ count: (prev?.count || 0) + ok.length, bytes: (prev?.bytes || 0) + freed }));
      setConfirm(null);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  /** " of college@…" when the removed copies are in accounts other than the one being worked in. */
  function otherAccountsNote(g) {
    const owners = [...new Set(g.files.filter((f) => f.id !== keep[g.id]).map((f) => f.account_email))]
      .filter((email) => email !== active?.email);
    return owners.length ? ` of ${owners.join(", ")}` : "";
  }

  if (!groups) return <Card bodyClassName="p-0"><SkeletonRows rows={8} /></Card>;

  const shown = filter ? groups.filter((g) => g.files.some((f) => String(f.account_id) === filter)) : groups;
  const copies = shown.filter((g) => !g.review_only);
  const crossCount = shown.filter((g) => g.kind === "cross_account").length;
  const recoverable = copies.reduce((s, g) => s + g.potential_recovery_bytes, 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Duplicates"
        description={
          multiple
            ? "Across all your linked accounts. Exact copies are matched by the checksum Google Drive stores for every file — not by name — including copies kept in different accounts. Files that only share a name are listed last as versions to review."
            : "Exact copies are matched by the SHA-256/MD5 checksum Google Drive stores for every file — not by name. Files that only share a name are listed last as versions to review."
        }
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Copy groups" value={copies.length} sub={multiple ? `${crossCount} span several accounts` : undefined} />
        <Stat label="Recoverable" value={formatBytes(recoverable)} tone="ok" sub="after each Drive Trash empties" />
        <Stat label="Version groups" value={shown.length - copies.length} sub="review only, not counted" />
        <Stat label="Accounts" value={multiple ? accounts.length : 1} sub={multiple ? "all linked accounts compared" : "link more under Accounts"} />
      </div>

      {multiple && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] text-faint" title="Pick an account to see only the groups that have at least one copy in it">
            Only show groups with a copy in
          </span>
          <FilterPills
            options={[{ value: "", label: `All accounts (${groups.length})` }, ...accounts.map((a) => ({
              value: String(a.id),
              label: `${short(a.email)} (${groups.filter((g) => g.files.some((f) => f.account_id === a.id)).length})`,
            }))]}
            value={filter}
            onChange={setFilter}
          />
        </div>
      )}

      {removed && (
        <DriveTrashNotice>
          Moved <span className="mono">{removed.count}</span> cop{removed.count === 1 ? "y" : "ies"} to Drive&apos;s Trash.{" "}
          <span className="mono">{formatBytes(removed.bytes)}</span> still counts against storage until each account&apos;s Trash is emptied — review
          there, then empty it to free the space now.
        </DriveTrashNotice>
      )}

      {shown.length === 0 ? (
        <Card><EmptyState icon={Copy} title="No duplicates found" subtitle={filter ? "None involve this account." : "Run a scan after adding files."} /></Card>
      ) : (
        shown.map((g) => {
          const cross = g.kind === "cross_account";
          const level = cross ? LEVEL.cross : LEVEL[g.match_level] || LEVEL.name;
          const keepId = keep[g.id];
          const removable = g.files.filter((f) => f.id !== keepId);
          const removableBytes = removable.reduce((s, f) => s + f.size_bytes, 0);
          const blocked = g.review_only && !ack[g.id];
          const showAccount = multiple || cross;
          return (
            <Card
              key={g.id}
              title={
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone={level.tone}><level.icon className="h-3 w-3" /> {level.label}</Badge>
                  <span className="mono text-[12px] font-normal text-faint">
                    {plural(g.files.length, "file", "files")}
                    {cross ? ` · in ${plural(g.accounts.length, "account", "accounts")}` : ""}
                  </span>
                  {!cross && multiple && <Badge tone={accountTone(accounts, g.account_id)}>{short(g.account_email)}</Badge>}
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
                      <th className="th w-14">Keep</th>
                      {showAccount && <th className="th">Account</th>}
                      <th className="th">Name</th><th className="th">Folder</th>
                      <th className="th text-right">Size</th><th className="th">Modified</th><th className="th">Checksum</th>
                      <th className="th w-16"><span className="sr-only">Links</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {g.files.map((f) => (
                      <tr
                        key={f.id}
                        className={`cursor-pointer ${keepId === f.id ? "bg-ok-soft/60" : "hover:bg-canvas"}`}
                        onClick={() =>
                          open({
                            kind: "Duplicate group member",
                            title: f.name,
                            subtitle: f.folder_path,
                            badges: [{ label: level.label, tone: level.tone }, ...(keepId === f.id ? [{ label: "Kept", tone: "ok" }] : [])],
                            fields: [
                              { label: "Account", value: f.account_email },
                              { label: "MIME type", value: f.mime_type, mono: true },
                              { label: "Size", value: formatBytes(f.size_bytes), mono: true },
                              { label: "Checksum", value: f.content_hash || "—", mono: true },
                              { label: "Modified", value: formatDate(f.modified_time) },
                              { label: "Drive ID", value: f.drive_id, mono: true },
                            ],
                            actions: [
                              { label: "Keep this copy", variant: "primary", onClick: () => setKeep((p) => ({ ...p, [g.id]: f.id })) },
                              ...driveLinkActions(f, links, f.account_email),
                            ],
                          })
                        }
                      >
                        <td className="td" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="radio"
                            name={`keep-${g.id}`}
                            checked={keepId === f.id}
                            onChange={() => setKeep((p) => ({ ...p, [g.id]: f.id }))}
                            className="accent-[rgb(var(--ok))]"
                            aria-label={`Keep ${f.name} in ${f.account_email}`}
                          />
                        </td>
                        {showAccount && (
                          <td className="td"><Badge tone={accountTone(accounts, f.account_id)}>{short(f.account_email)}</Badge></td>
                        )}
                        <td className="td max-w-[280px] truncate font-medium" title={f.name}>{f.name}</td>
                        <td className="td max-w-[220px] truncate text-sub">{f.folder_path || "—"}</td>
                        <td className="td mono text-right">{formatBytes(f.size_bytes)}</td>
                        <td className="td whitespace-nowrap text-sub">{formatDate(f.modified_time)}</td>
                        <td className="td mono text-[12px] text-sub">{shortHash(f.content_hash)}</td>
                        <td className="td py-0 text-right"><DriveFileLinks file={f} account={f.account_email} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-2.5">
                <span className="text-[12px] text-faint">
                  {cross && keepId === g.recommended_keep_file_id ? "Suggested: keep the copy in the account with the most free space." : ""}
                </span>
                <div className="flex flex-wrap items-center gap-3">
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
              </div>
            </Card>
          );
        })
      )}

      <ConfirmDialog
        open={!!confirm}
        danger
        title={confirm ? `Move ${confirm.files.filter((f) => f.id !== keep[confirm.id]).length} file(s) to Drive's Trash?` : ""}
        description={confirm ? describe(confirm, keep[confirm.id], multiple) : ""}
        consequences={[
          { kind: "undoable", text: "Restore any of them from History & Restore (in the account each was in), or from Drive's Trash." },
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

function describe(g, keepId, multiple) {
  const kept = g.files.find((f) => f.id === keepId);
  const where = (f) => (multiple ? ` (${f.account_email})` : "");
  const removing = g.files.filter((f) => f.id !== keepId).map((f) => `${f.name}${where(f)}`).join(", ");
  return `Keeping “${kept?.name}”${kept ? where(kept) : ""}. Moving to Trash: ${removing}.`;
}
