import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeftRight, CircleCheck, Plus, TriangleAlert, UserMinus } from "lucide-react";
import { api } from "../services/api.js";
import { accountTone, useAccounts } from "../context/accounts.jsx";
import { useScan } from "../context/scan.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, Legend, Notice, PageHeader, SegmentedBar, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import { Avatar } from "../components/shell/ProfileMenu.jsx";
import { CONNECT_ERRORS } from "./Connect.jsx";
import { formatBytes, formatDateTime } from "../utils/format.js";

const TONE_VAR = { accent: "--accent", ok: "--ok", warn: "--warn", info: "--info" };
const AVATAR = {
  accent: "bg-accent-soft text-accent-ink", ok: "bg-ok-soft text-ok-ink", warn: "bg-warn-soft text-warn-ink", info: "bg-info-soft text-info-ink",
};
const LINK_ERRORS = {
  ...CONNECT_ERRORS,
  demo_link: "Demo Mode links simulated accounts only. Connect a Google account first to link your real ones.",
  access_denied: "You cancelled the Google sign-in, so no account was added.",
};

/** Every Google account linked to this profile and their combined usage. Files copied across
 * accounts are listed with the other duplicates, on the Duplicates page. */
export default function Accounts() {
  const { summary, accounts, switchTo, remove, addAccount, adding } = useAccounts();
  const { version } = useScan();
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const [saved, setSaved] = useState(null); // all-time History totals over every linked account
  const [removing, setRemoving] = useState(null); // an account to remove from the profile
  const [busy, setBusy] = useState(false);

  const linked = params.get("linked");
  const error = params.get("error") ? LINK_ERRORS[params.get("error")] || "Something went wrong." : null;

  useEffect(() => {
    api.getHistorySummary().then(setSaved, () => setSaved(null));
  }, [version, accounts.length]);

  const segments = useMemo(
    () => accounts.filter((a) => a.used_bytes != null).map((a) => ({
      key: String(a.id), label: a.email, value: a.used_bytes,
      color: `rgb(var(${TONE_VAR[accountTone(accounts, a.id)]}))`,
    })),
    [accounts],
  );

  if (!summary) return <Card bodyClassName="p-0"><SkeletonRows rows={6} /></Card>;
  const { combined } = summary;
  // Free space only exists in personal accounts' own quotas; a school/work
  // account's storage is its organization's shared pool, not yours.
  const free = combined.free_bytes ?? combined.quota_bytes - combined.used_bytes;
  const pooled = combined.pooled_accounts || 0;

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
        description="Every Google account linked to this profile. Each is scanned with its own permission. Duplicates, Organize, Compression, History and Analytics cover all of them; the Dashboard and Settings show the one you're working in (switch from the top-right menu)."
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
        <Stat label="Used across accounts" value={formatBytes(combined.used_bytes)}
              sub={pooled
                ? `${formatBytes(combined.quota_bytes)} personal quota + ${pooled} school/work account${pooled === 1 ? "" : "s"}`
                : `of ${formatBytes(combined.quota_bytes)}`} />
        <Stat label="Free across accounts" value={formatBytes(Math.max(0, free))} tone="ok"
              sub={pooled ? "personal accounts only; not poolable" : "but not poolable: 15 GB each"} />
        <Stat label="Saved by CloudClean" value={formatBytes(saved?.saved_bytes || 0)} tone={saved?.saved_bytes ? "ok" : undefined}
              sub={saved ? `all accounts, all time · ${saved.actions} action${saved.actions === 1 ? "" : "s"}` : "all accounts, all time"} />
      </div>

      <Card title="Storage by account" subtitle="Google gives every account its own quota; a full account can't borrow another's free space.">
        {segments.length > 0 && (
          <>
            <SegmentedBar segments={segments} total={Math.max(combined.quota_bytes, combined.used_bytes)} height="h-3" />
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
                    {a.pooled && <Badge tone="info">School/work</Badge>}
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    {a.pooled ? (
                      <span
                        className="mono text-[11px] text-sub"
                        title={a.org_quota_bytes ? `Whole organization: ${formatBytes(a.org_used_bytes)} of ${formatBytes(a.org_quota_bytes)}` : undefined}
                      >
                        {formatBytes(a.used_bytes)} in your Drive · storage shared by {a.email.split("@")[1]}, no personal limit
                      </span>
                    ) : (
                      <>
                        <div className="h-1.5 w-40 overflow-hidden rounded-sm bg-track">
                          <div className={pct >= 90 ? "h-full bg-bad" : pct >= 75 ? "h-full bg-warn" : "h-full bg-accent"} style={{ width: `${Math.min(100, pct)}%` }} />
                        </div>
                        <span className="mono text-[11px] text-sub">
                          {a.quota_bytes ? `${formatBytes(a.used_bytes)} / ${formatBytes(a.quota_bytes)}` : "not scanned yet"}
                        </span>
                      </>
                    )}
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
        {accounts.length > 1 && (
          <p className="mt-3 text-[12px] text-sub">
            Files stored in more than one of these accounts are listed in{" "}
            <Link to="/duplicates" className="font-medium text-accent-ink hover:underline">Duplicates</Link>, with the account each copy is in.
          </p>
        )}
      </Card>

      <ConfirmDialog
        open={!!removing}
        title={removing ? `Remove ${removing.email} from this profile?` : ""}
        description="Its files in Google Drive aren't touched."
        consequences={removing?.is_demo
          ? [{ kind: "permanent", text: "This simulated account and its demo data are deleted." }]
          : [
              { kind: "undoable", text: "It stays connected on its own — sign in with it, or add it here again, any time." },
              { kind: "info", text: "Its files no longer count in “across accounts” totals, Duplicates, Analytics or History here." },
            ]}
        confirmLabel="Remove from profile"
        busy={busy}
        onConfirm={removeAccount}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
