import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Image, KeyRound, Mail, Paperclip, RotateCcw, Trash2 } from "lucide-react";
import { api } from "../services/api.js";
import { useScan } from "../context/scan.jsx";
import { useDrawer } from "../context/drawer.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { useGoogleLinks } from "../hooks/useGoogleLinks.js";
import { GmailTrashLink, IconLink } from "../components/GoogleLinks.jsx";
import { DEMO_LINK_REASON } from "../components/details.js";
import { Button, buttonVariants } from "../components/ui/button.jsx";
import { Card, EmptyState, FilterPills, PageHeader, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
import { Checkbox } from "../components/ui/controls.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import BatchDock from "../components/shell/BatchDock.jsx";
import { formatBytes, formatDate } from "../utils/format.js";

const AGES = [
  { value: 0, label: "All large emails" },
  { value: 365, label: "Older than 1 year" },
  { value: 1095, label: "Older than 3 years" },
];
const PAGE_SIZE = 50;

export default function Gmail() {
  const [age, setAge] = useState(0);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [trashed, setTrashed] = useState([]);
  const [selected, setSelected] = useState(new Map());
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const { version } = useScan();
  const { open } = useDrawer();
  const toast = useToast();
  const links = useGoogleLinks();

  const load = useCallback(async () => {
    const [mail, history] = await Promise.all([api.getGmail({ older_than_days: age, page, page_size: PAGE_SIZE }), api.getHistory()]);
    setData(mail);
    setTrashed(history.filter((h) => h.action === "gmail_trashed" && h.restorable));
  }, [age, page]);

  useEffect(() => {
    load().catch((e) => toast(e.message, "error"));
  }, [load, version, toast]);

  function toggle(m) {
    setSelected((prev) => {
      const next = new Map(prev);
      next.has(m.id) ? next.delete(m.id) : next.set(m.id, m);
      return next;
    });
  }

  async function trash() {
    setBusy(true);
    try {
      const res = await api.trashGmail([...selected.keys()]);
      const ok = res.trashed.filter((r) => r.success);
      const failed = res.trashed.length - ok.length;
      toast(
        failed ? `Moved ${ok.length} email(s) to Trash; ${failed} couldn't be moved.` : `Moved ${ok.length} email(s) to Gmail Trash.`,
        failed ? "error" : "success",
      );
      setSelected(new Map());
      setConfirming(false);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function restore(h) {
    try {
      toast((await api.restoreAction(h.id)).message || "Restored.");
      await load();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  const messages = data?.messages || [];
  const selectedBytes = [...selected.values()].reduce((s, m) => s + m.size_bytes, 0);
  const allChecked = messages.length > 0 && messages.every((m) => selected.has(m.id));

  return (
    <div className="space-y-4">
      <PageHeader title="Gmail & Photos" description="Gmail and Google Photos share the same 15 GB as Drive. CloudClean reads only size, sender, subject and date — never message bodies." />

      {data?.access === "not_granted" ? (
        <Card>
          <EmptyState
            icon={KeyRound}
            title="Gmail access wasn't granted"
            subtitle="You connected without the Gmail permission. Reconnect and tick Gmail — Drive keeps working either way."
            action={<Button variant="primary" onClick={() => (window.location.href = api.googleLoginUrl)}>Reconnect Google account</Button>}
          />
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Stat label={`Emails ≥ ${data?.min_mb ?? "…"} MB`} value={data ? data.total : "—"} />
            <Stat label="Size" value={data ? formatBytes(data.total_bytes) : "—"} />
            <Stat label="In Gmail Trash (restorable)" value={trashed.length} className="col-span-2 lg:col-span-1" />
          </div>

          <FilterPills options={AGES} value={age} onChange={(v) => { setAge(v); setPage(1); setSelected(new Map()); }} />

          <Card bodyClassName="p-0">
            {!data ? (
              <SkeletonRows rows={8} cols={5} />
            ) : messages.length === 0 ? (
              <EmptyState icon={Mail} title="No large emails" subtitle="Run a scan to check Gmail, or lower the size threshold in Settings." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead className="border-b border-line">
                    <tr>
                      <th className="th w-8">
                        <Checkbox
                          label="Select all on this page"
                          checked={allChecked}
                          onChange={(on) => setSelected(() => (on ? new Map(messages.map((m) => [m.id, m])) : new Map()))}
                        />
                      </th>
                      <th className="th">Subject</th><th className="th">From</th><th className="th">Received</th>
                      <th className="th text-right">Size</th><th className="th" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {messages.map((m) => (
                      <tr
                        key={m.id}
                        className="cursor-pointer hover:bg-canvas"
                        onClick={() =>
                          open({
                            kind: "Large email",
                            title: m.subject,
                            subtitle: m.sender,
                            fields: [
                              { label: "Size", value: formatBytes(m.size_bytes), mono: true },
                              { label: "Received", value: formatDate(m.received_time) },
                              { label: "Age", value: `${m.inactivity_days} days`, mono: true },
                              { label: "Attachments", value: m.has_attachment ? "Yes" : "No" },
                              { label: "Labels", value: m.labels || "—", mono: true },
                            ],
                            reason: "Save any attachment you still need to Drive before trashing the email.",
                            actions: [{ label: "Open in Gmail", icon: ExternalLink, href: links.gmailMessage(m.web_url), disabledReason: DEMO_LINK_REASON }],
                          })
                        }
                      >
                        <td className="td w-8"><Checkbox label={`Select ${m.subject}`} checked={selected.has(m.id)} onChange={() => toggle(m)} /></td>
                        <td className="td max-w-[340px]">
                          <div className="flex items-center gap-1.5 truncate font-medium">
                            {m.has_attachment && <Paperclip className="h-3.5 w-3.5 shrink-0 text-faint" />}
                            <span className="truncate">{m.subject}</span>
                          </div>
                        </td>
                        <td className="td max-w-[220px] truncate text-sub">{m.sender}</td>
                        <td className="td whitespace-nowrap text-sub">{formatDate(m.received_time)}</td>
                        <td className="td mono text-right">{formatBytes(m.size_bytes)}</td>
                        <td className="td w-8 py-0">
                          <IconLink href={links.gmailMessage(m.web_url)} label="Open in Gmail" icon={ExternalLink} disabledReason={DEMO_LINK_REASON} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {data && data.total > PAGE_SIZE && (
              <div className="flex items-center justify-end gap-1 border-t border-line px-4 py-2">
                <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button size="sm" disabled={page * PAGE_SIZE >= data.total} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            )}
          </Card>

          {trashed.length > 0 && (
            <Card
              title="Recently moved to Gmail Trash"
              subtitle="Restorable until Gmail empties its Trash (30 days). Emptying it there frees the space now."
              action={<GmailTrashLink />}
              bodyClassName="p-0"
            >
              <ul className="divide-y divide-line">
                {trashed.map((h) => (
                  <li key={h.id} className="flex items-center justify-between gap-3 px-4 py-2">
                    <span className="min-w-0 truncate text-[13px]">{h.file_name}</span>
                    <span className="mono shrink-0 text-[12px] text-sub">{formatBytes(h.original_size_bytes)}</span>
                    <Button size="sm" onClick={() => restore(h)}><RotateCcw className="h-3.5 w-3.5" /> Restore</Button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}

      <Card title="Google Photos" subtitle="Read-only for third-party apps since Google restricted the Photos Library API (March 2025).">
        <p className="text-[13px] text-sub">
          CloudClean can show how much Gmail and Photos use together (Dashboard), but it can't list or clean individual photos.
          Google's own storage manager can.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <a href={links.account("https://one.google.com/storage/management")} target="_blank" rel="noreferrer" className={buttonVariants({ size: "sm" })}>
            <ExternalLink className="h-3.5 w-3.5" /> Google storage manager
          </a>
          <a href={links.account("https://photos.google.com/")} target="_blank" rel="noreferrer" className={buttonVariants({ size: "sm" })}>
            <Image className="h-3.5 w-3.5" /> Google Photos
          </a>
        </div>
      </Card>

      <BatchDock count={selected.size} bytes={selectedBytes} actionLabel="Move to Trash" actionIcon={Trash2} danger onAction={() => setConfirming(true)} onClear={() => setSelected(new Map())} />

      <ConfirmDialog
        open={confirming}
        danger
        title={`Move ${selected.size} email${selected.size === 1 ? "" : "s"} to Gmail Trash?`}
        description={`${formatBytes(selectedBytes)} in total. Save any attachments you still need first.`}
        consequences={[
          { kind: "undoable", text: "Restore them here or from History & Restore while they're in Gmail Trash." },
          { kind: "permanent", text: "Gmail empties its Trash after 30 days — the emails are gone after that." },
        ]}
        confirmLabel="Move to Trash"
        busy={busy}
        onConfirm={trash}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
