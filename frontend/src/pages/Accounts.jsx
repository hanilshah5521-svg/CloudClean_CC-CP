import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowLeftRight, CircleCheck, Copy, Plus, Trash2, TriangleAlert, UserMinus } from "lucide-react";
import { api } from "../services/api.js";
import { accountTone, useAccounts } from "../context/accounts.jsx";
import { useScan } from "../context/scan.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, FilterPills, Legend, Notice, PageHeader, SegmentedBar, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import { DriveFileLinks } from "../components/GoogleLinks.jsx";
import { Avatar } from "../components/shell/ProfileMenu.jsx";
import { CONNECT_ERRORS } from "./Connect.jsx";
import { formatBytes, formatDate, formatDateTime, shortHash } from "../utils/format.js";

const TONE_VAR = { accent: "--accent", ok: "--ok", warn: "--warn", info: "--info" };
const AVATAR = {
  accent: "bg-accent-soft text-accent-ink", ok: "bg-ok-soft text-ok-ink", warn: "bg-warn-soft text-warn-ink", info: "bg-info-soft text-info-ink",
};
const LINK_ERRORS = {
  ...CONNECT_ERRORS,
  demo_link: "Demo Mode links simulated accounts only. Connect a Google account first to link your real ones.",
  access_denied: "You cancelled the Google sign-in, so no account was added.",
};

/** Every Google account linked to this profile, their combined usage, and files copied across them. */
export default function Accounts() {
  const { summary, accounts, switchTo, remove, addAccount, adding } = useAccounts();
  const { version } = useScan();
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const [dups, setDups] = useState(null);
  const [filter, setFilter] = useState("");
  const [keep, setKeep] = useState({});
  const [confirm, setConfirm] = useState(null); // a duplicate group to clean up
  const [removing, setRemoving] = useState(null); // an account to remove from the profile
  const [busy, setBusy] = useState(false);

  const linked = params.get("linked");
  const error = params.get("error") ? LINK_ERRORS[params.get("error")] || "Something went wrong." : null;

  const loadDups = useCallback(async () => {
    const data = await api.getCrossDuplicates(filter || undefined);
    setDups(data);
    setKeep((prev) => {
      const next = { ...prev };
      for (const g of data.groups) if (!(g.key in next)) next[g.key] = g.recommended_keep_id;
      return next;
    });
  }, [filter]);

  useEffect(() => {
    loadDups().catch((e) => toast(e.message, "error"));
  }, [loadDups, version, accounts.length, toast]);

  const segments = useMemo(
    () => accounts.filter((a) => a.used_bytes != null).map((a) => ({
      key: String(a.id), label: a.email, value: a.used_bytes,
      color: `rgb(var(${TONE_VAR[accountTone(accounts, a.id)]}))`,
    })),
    [accounts],
  );

  if (!summary) return <Card bodyClassName="p-0"><SkeletonRows rows={6} /></Card>;
  const { combined } = summary;
  const free = combined.quota_bytes - combined.used_bytes;

  async function removeCopies() {
    const g = confirm;
    const keepId = keep[g.key];
    setBusy(true);
    try {
      const { results } = await api.removeCrossCopies(keepId, g.files.filter((f) => f.id !== keepId).map((f) => f.id));
      const ok = results.filter((r) => r.success);
      const failed = results.length - ok.length;
      const copies = (n) => `${n} cop${n === 1 ? "y" : "ies"}`;
      toast(
        failed
          ? `Moved ${copies(ok.length)} to Trash; ${failed} couldn't be moved — see that account's History.`
          : `Moved ${copies(ok.length)} to Trash in ${[...new Set(ok.map((r) => r.account_email))].join(", ")} — ${formatBytes(ok.reduce((s, r) => s + r.saved_bytes, 0))} freed once its Trash is emptied.`,
        failed ? "error" : "success",
      );
      setConfirm(null);
      await loadDups();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function removeAccount() {
    setBusy(true);
    try {
      await remove(removing.id);
      setRemoving(null);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  const addLabel = summary.add_kind === "simulated" ? "Add a simulated account" : "Add Google account";
  const dismiss = () => setParams({}, { replace: true });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Accounts"
        description="Every Google account linked to this profile. Each is scanned with its own permission; you work in one at a time and switch from the top-right menu."
        actions={
          <Button variant="primary" onClick={addAccount} disabled={!summary.can_add || adding}>
            <Plus className="h-3.5 w-3.5" /> {adding ? "Adding…" : addLabel}
          </Button>
        }
      />

      {linked && <Notice tone="ok" icon={CircleCheck}><span>Linked <span className="mono">{linked}</span>. Run Scan to analyze it. </span><button className="underline" onClick={dismiss}>Dismiss</button></Notice>}
      {error && <Notice tone="bad" icon={TriangleAlert}><span>{error} </span><button className="underline" onClick={dismiss}>Dismiss</button></Notice>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Linked accounts" value={accounts.length} sub={`${combined.scanned_accounts} scanned`} />
        <Stat label="Used across accounts" value={formatBytes(combined.used_bytes)} sub={`of ${formatBytes(combined.quota_bytes)}`} />
        <Stat label="Free across accounts" value={formatBytes(Math.max(0, free))} tone="ok" sub="but not poolable: 15 GB each" />
        <Stat label="Copies across accounts" value={formatBytes(dups?.removable_bytes || 0)} tone={dups?.removable_bytes ? "warn" : undefined}
              sub={`${dups?.groups.length ?? 0} files stored more than once`} />
      </div>

      <Card title="Storage by account" subtitle="Google gives every account its own quota; a full account can't borrow another's free space.">
        {segments.length > 0 && (
          <>
            <SegmentedBar segments={segments} total={combined.quota_bytes} height="h-3" />
            <Legend items={segments} />
          </>
        )}
        <ul className="mt-4 divide-y divide-line rounded border border-line">
          {accounts.map((a) => {
            const tone = accountTone(accounts, a.id);
            const pct = a.quota_bytes ? (a.used_bytes / a.quota_bytes) * 100 : 0;
            return (
              <li key={a.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                <Avatar email={a.email} className={AVATAR[tone]} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-[13px] font-medium text-ink">{a.email}</span>
                    {a.active && <Badge tone="accent">Working in this one</Badge>}
                    {a.is_demo && <Badge>Simulated</Badge>}
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="h-1.5 w-40 overflow-hidden rounded-sm bg-track">
                      <div className={pct >= 90 ? "h-full bg-bad" : pct >= 75 ? "h-full bg-warn" : "h-full bg-accent"} style={{ width: `${Math.min(100, pct)}%` }} />
                    </div>
                    <span className="mono text-[11px] text-sub">
                      {a.quota_bytes ? `${formatBytes(a.used_bytes)} / ${formatBytes(a.quota_bytes)}` : "not scanned yet"}
                    </span>
                    <span className="text-[11px] text-faint">{a.scanned_at ? `· scanned ${formatDateTime(a.scanned_at)}` : ""}</span>
                  </div>
                </div>
                {!a.active && (
                  <div className="flex gap-1">
                    <Button size="sm" onClick={() => switchTo(a.id)}><ArrowLeftRight className="h-3.5 w-3.5" /> Switch</Button>
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(a)}><UserMinus className="h-3.5 w-3.5" /> Remove</Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Card>

      <Card
        title="Copies across accounts"
        subtitle="Byte-identical files (same checksum and size) stored in more than one of your accounts. Each copy counts against its own account's 15 GB."
        bodyClassName="p-0"
      >
        {accounts.length > 1 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
            <span className="text-[12px] text-faint">Show copies involving</span>
            <FilterPills
              options={[{ value: "", label: "All accounts" }, ...accounts.map((a) => ({ value: String(a.id), label: a.email.split("@")[0] }))]}
              value={filter}
              onChange={setFilter}
            />
          </div>
        )}
        {accounts.length < 2 ? (
          <EmptyState icon={Copy} title="Link another account to compare"
                      subtitle="Add the other Google accounts you use, then Run Scan: files copied between them show up here."
                      action={<Button variant="primary" onClick={addAccount} disabled={!summary.can_add || adding}><Plus className="h-3.5 w-3.5" /> {addLabel}</Button>} />
        ) : !dups ? (
          <SkeletonRows rows={5} />
        ) : dups.groups.length === 0 ? (
          <EmptyState icon={Copy} title="No copies across accounts" subtitle="Run Scan after adding files: every linked account is compared by checksum." />
        ) : (
          <div className="divide-y divide-line">
            {dups.groups.map((g) => {
              const keepId = keep[g.key];
              const others = g.files.filter((f) => f.id !== keepId);
              return (
                <section key={g.key} className="px-4 py-3">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="flex flex-wrap items-center gap-2 text-[12px] text-sub">
                      <Badge tone="ok">Identical · checksum <span className="mono">{shortHash(g.content_hash)}</span></Badge>
                      <span className="mono">{formatBytes(g.size_bytes)}</span> each · in {g.accounts.length} accounts
                    </span>
                    <span className="text-[12px] text-sub">Frees <span className="mono text-ok-ink">{formatBytes(others.reduce((s, f) => s + f.size_bytes, 0))}</span></span>
                  </div>
                  <div className="overflow-x-auto rounded border border-line">
                    <table className="w-full text-[13px]">
                      <thead className="border-b border-line">
                        <tr>
                          <th className="th w-14">Keep</th><th className="th">Account</th><th className="th">Name</th>
                          <th className="th">Folder</th><th className="th">Modified</th><th className="th w-16"><span className="sr-only">Links</span></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {g.files.map((f) => (
                          <tr key={f.id} className={keepId === f.id ? "bg-ok-soft/60" : ""}>
                            <td className="td">
                              <input type="radio" name={`keep-${g.key}`} checked={keepId === f.id} aria-label={`Keep the copy in ${f.account_email}`}
                                     onChange={() => setKeep((p) => ({ ...p, [g.key]: f.id }))} className="accent-[rgb(var(--ok))]" />
                            </td>
                            <td className="td"><Badge tone={accountTone(accounts, f.account_id)}>{f.account_email.split("@")[0]}</Badge></td>
                            <td className="td max-w-[260px] truncate font-medium" title={f.name}>{f.name}</td>
                            <td className="td max-w-[200px] truncate text-sub">{f.folder_path || "—"}</td>
                            <td className="td text-sub">{formatDate(f.modified_time)}</td>
                            <td className="td py-0 text-right"><DriveFileLinks file={f} account={f.account_email} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[12px] text-faint">
                      {keepId === g.recommended_keep_id ? "Suggested: keep the copy in the account with the most free space." : "You chose which copy to keep."}
                    </span>
                    <Button variant="danger" size="sm" onClick={() => setConfirm(g)}>
                      <Trash2 className="h-3.5 w-3.5" /> Remove {others.length} other cop{others.length === 1 ? "y" : "ies"}
                    </Button>
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={!!confirm}
        danger
        title={confirm ? `Remove ${confirm.files.length - 1} cop${confirm.files.length === 2 ? "y" : "ies"} of “${confirm.files.find((f) => f.id === keep[confirm.key])?.name}”?` : ""}
        description={confirm ? `Keeping the copy in ${confirm.files.find((f) => f.id === keep[confirm.key])?.account_email}. Removing: ${confirm.files.filter((f) => f.id !== keep[confirm.key]).map((f) => `${f.name} (${f.account_email})`).join(", ")}.` : ""}
        consequences={[
          { kind: "undoable", text: "Each copy moves to its own account's Drive Trash — restore it from that account's History & Restore." },
          { kind: "permanent", text: "Google empties each Trash after 30 days; after that only the kept copy remains." },
          { kind: "info", text: "Space frees in each account once its Trash is emptied. Links to the removed copies stop working." },
        ]}
        confirmLabel="Move copies to Trash"
        busy={busy}
        onConfirm={removeCopies}
        onCancel={() => setConfirm(null)}
      />

      <ConfirmDialog
        open={!!removing}
        title={removing ? `Remove ${removing.email} from this profile?` : ""}
        description="Its files in Google Drive aren't touched."
        consequences={removing?.is_demo
          ? [{ kind: "permanent", text: "This simulated account and its demo data are deleted." }]
          : [
              { kind: "undoable", text: "It stays connected on its own — sign in with it, or add it here again, any time." },
              { kind: "info", text: "Its files no longer count in “across accounts” totals or duplicates." },
            ]}
        confirmLabel="Remove from profile"
        busy={busy}
        onConfirm={removeAccount}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
