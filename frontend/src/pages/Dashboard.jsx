import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Archive, ChevronRight, Copy, Film, RefreshCw, ScanSearch, Search } from "lucide-react";
import { api } from "../services/api.js";
import { useScan } from "../context/scan.jsx";
import { useAccounts } from "../context/accounts.jsx";
import { useDrawer } from "../context/drawer.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, Legend, PageHeader, SegmentedBar, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
import { JobStatus } from "../components/ui/progress.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { DriveTrashNotice } from "../components/GoogleLinks.jsx";
import { driveLinkActions } from "../components/details.js";
import { useGoogleLinks } from "../hooks/useGoogleLinks.js";
import { formatBytes, formatDate } from "../utils/format.js";

export const REC_TYPE = {
  compress: { label: "Compress", icon: Film, to: "/compression" },
  duplicate: { label: "Remove duplicates", icon: Copy, to: "/duplicates" },
  archive: { label: "Archive inactive files", icon: Archive },
  review: { label: "Review large file", icon: Search },
};
const RISK_TONE = { low: "ok", medium: "warn", high: "bad" };
const DEDUCTIONS = [
  ["duplicate_inefficiency", "Duplicate copies"],
  ["compression_opportunity", "Compressible files"],
  ["inactive_data", "Inactive data"],
  ["large_file_concentration", "Large-file concentration"],
];

function excerpt(reason) {
  return reason.replace(/^Compression recommended because:\s*/i, "").replace(/\n-?\s*/g, " · ").trim();
}

export default function Dashboard() {
  const { version, scanning, job, runDrive } = useScan();
  const { open, close } = useDrawer();
  const navigate = useNavigate();
  const links = useGoogleLinks();
  const toast = useToast();
  const { multiple, accounts, active, summary } = useAccounts();
  const [data, setData] = useState(null);
  const [archiving, setArchiving] = useState(null); // files awaiting the archive confirmation
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [storage, analysis, recs, history] = await Promise.all([
      api.getStorage(), api.getAnalysis(), api.getRecommendations(), api.getHistory(),
    ]);
    // Gmail recommendations from earlier scans are hidden: CloudClean now works on Drive only.
    setData({ storage, analysis, recs: recs.filter((r) => r.type !== "gmail"), history: history.slice(0, 6) });
  }, []);

  useEffect(() => {
    load().catch(() => setData({ error: true }));
  }, [load, version]);

  if (!data) return <Card bodyClassName="p-0"><SkeletonRows rows={8} /></Card>;
  const { storage, analysis, recs, history } = data;

  if (!analysis?.analyzed) {
    return (
      <div className="space-y-5">
        <PageHeader title="Dashboard" description="Drive, Gmail and Photos share one storage quota. Run a scan to see where yours goes." />
        <Card>
          {scanning ? (
            <JobStatus job={job} />
          ) : (
            <EmptyState
              icon={ScanSearch}
              title="No analysis yet"
              subtitle="A scan reads file metadata only (names, sizes, dates, checksums) — never file contents — and builds the recommendations."
              action={<Button variant="primary" onClick={runDrive}><RefreshCw className="h-3.5 w-3.5" /> Run Scan</Button>}
            />
          )}
        </Card>
      </div>
    );
  }

  const segments = [
    { key: "drive", label: "Google Drive", value: storage.drive_bytes, color: "rgb(var(--tier-drive))" },
    { key: "trash", label: "Drive Trash", value: storage.drive_trash_bytes, color: "rgb(var(--tier-trash))" },
    { key: "gmail", label: "Gmail + Photos", value: storage.gmail_photos_bytes, color: "rgb(var(--tier-gmail))" },
  ];
  const score = Math.round(analysis.optimization_score);

  async function openArchive(rec, rank) {
    const { files } = await api.getArchiveCandidates();
    const total = files.reduce((s, f) => s + f.size_bytes, 0);
    open({
      kind: `Recommendation #${rank}`,
      title: `Archive ${files.length} inactive file${files.length === 1 ? "" : "s"}`,
      badges: [{ label: `${rec.risk} risk`, tone: RISK_TONE[rec.risk] }, { label: `${Math.round(rec.confidence * 100)}% confidence`, tone: "neutral" }],
      fields: [
        { label: "Est. saving", value: formatBytes(rec.estimated_saving_bytes), mono: true },
        { label: "Files", value: `${files.length} · ${formatBytes(total)}`, mono: true },
      ],
      reason: rec.reason,
      body: (
        <ul className="divide-y divide-line rounded border border-line text-[12px]">
          {files.map((f) => (
            <li key={f.id} className="flex items-baseline justify-between gap-3 px-3 py-1.5">
              <span className="min-w-0">
                <span className="block truncate text-ink">{f.name}</span>
                {f.folder_path && <span className="block truncate text-[11px] text-faint">{f.folder_path}</span>}
              </span>
              <span className="mono shrink-0 text-sub">{formatBytes(f.size_bytes)}</span>
            </li>
          ))}
        </ul>
      ),
      actions: files.length
        ? [{ label: `Archive ${files.length} into one ZIP`, variant: "primary", icon: Archive, onClick: () => setArchiving(files) }]
        : [],
    });
  }

  async function archive() {
    setBusy(true);
    try {
      const res = await api.archiveFiles(archiving.map((f) => f.id), `cloudclean_archive_${new Date().toISOString().slice(0, 10)}.zip`);
      toast(
        res.failed?.length
          ? `Archive created, but ${res.failed.length} original(s) couldn't be moved to Trash. See History.`
          : `Archived ${archiving.length} files into ${res.archive_name} — saves ${formatBytes(res.saved_bytes)} once Drive's Trash is emptied.`,
        res.failed?.length ? "error" : "success",
      );
      setArchiving(null);
      close();
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function openRec(rec, rank) {
    if (rec.type === "archive") return openArchive(rec, rank).catch((e) => toast(e.message, "error"));
    const meta = REC_TYPE[rec.type] || REC_TYPE.review;
    open({
      kind: `Recommendation #${rank}`,
      title: rec.file_name ? `${meta.label}: ${rec.file_name}` : meta.label,
      badges: [{ label: `${rec.risk} risk`, tone: RISK_TONE[rec.risk] }, { label: `${Math.round(rec.confidence * 100)}% confidence`, tone: "neutral" }],
      fields: [
        { label: "Est. saving", value: rec.estimated_saving_bytes ? formatBytes(rec.estimated_saving_bytes) : "Review only — not counted", mono: true },
        { label: "Action", value: rec.action },
      ],
      reason: rec.reason,
      actions: [
        ...(meta.to ? [{ label: `Open ${meta.label.toLowerCase()}`, variant: "primary", icon: ChevronRight, onClick: () => navigate(meta.to) }] : []),
        ...(rec.file_drive_id
          ? driveLinkActions({ drive_id: rec.file_drive_id, web_url: rec.file_web_url, parent_id: rec.file_parent_id }, links)
          : []),
      ],
    });
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Dashboard" description={`Last scan ${formatDate(analysis.completed_at)} · ${analysis.files_analyzed} files analyzed`} />

      {multiple && summary && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-surface px-4 py-2.5 text-[12px] text-sub">
          <span>
            Showing <span className="font-medium text-ink">{active?.email}</span>. Across your{" "}
            <span className="mono text-ink">{accounts.length}</span> linked accounts:{" "}
            <span className="mono text-ink">{formatBytes(summary.combined.used_bytes)}</span> of{" "}
            <span className="mono text-ink">{formatBytes(summary.combined.quota_bytes)}</span> used.
          </span>
          <Link to="/accounts" className="font-medium text-accent-ink hover:underline">All accounts &amp; shared duplicates →</Link>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Used" value={formatBytes(storage.used_bytes)} sub={`of ${formatBytes(storage.quota_bytes)} · ${storage.used_percent}%`} tone={storage.used_percent >= 90 ? "bad" : undefined} />
        <Stat label="Potentially recoverable" value={`+${formatBytes(storage.recoverable_bytes)}`} sub="counted once per file" tone="ok" />
        <Stat label="After optimization" value={formatBytes(storage.projected_used_bytes)} sub={`${storage.projected_used_percent}% · once Trash is emptied`} />
        <Stat label="Recommendations" value={recs.length} sub={`${analysis.duplicates_found} duplicate files found`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card title="Shared storage quota" subtitle="Google reports Drive and its Trash separately; Gmail and Photos only as one number.">
          <SegmentedBar segments={segments} total={storage.quota_bytes} marker={storage.projected_used_bytes} height="h-3" />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <Legend items={segments} />
            <span className="text-[12px] text-sub">
              Free{" "}<span className="mono text-ink">{formatBytes(storage.remaining_bytes)}</span>
            </span>
          </div>
          {storage.drive_trash_bytes > 0 && (
            <DriveTrashNotice className="mt-3">
              <span className="mono">{formatBytes(storage.drive_trash_bytes)}</span> is in Drive&apos;s Trash and still counts until it&apos;s emptied —
              Google does that automatically after 30 days.
            </DriveTrashNotice>
          )}
        </Card>

        <Card title="Optimization score" subtitle="100 minus four capped, weighted deductions.">
          <div className="flex items-center gap-4">
            <ScoreGauge score={score} />
            <ul className="min-w-0 flex-1 space-y-1.5">
              {DEDUCTIONS.map(([key, label]) => (
                <li key={key} className="flex items-baseline justify-between gap-2 text-[12px]">
                  <span className="truncate text-sub">{label}</span>
                  <span className="mono text-bad-ink">−{analysis.score_breakdown?.[key] ?? 0}</span>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      </div>

      <Card title="Recommendations" subtitle="Ranked by estimated saving. Select one for the full reasoning." bodyClassName="p-0">
        {recs.length === 0 ? (
          <EmptyState title="Nothing to optimize" subtitle="Your Drive is in good shape. Scan again after adding files." />
        ) : (
          <ol className="divide-y divide-line">
            {recs.slice(0, 12).map((rec, i) => {
              const meta = REC_TYPE[rec.type] || REC_TYPE.review;
              return (
                <li key={rec.id}>
                  <button onClick={() => openRec(rec, i + 1)} className="tactile flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-canvas">
                    <span className="mono w-6 shrink-0 text-[12px] text-faint">{String(i + 1).padStart(2, "0")}</span>
                    <meta.icon className="h-4 w-4 shrink-0 text-sub" strokeWidth={1.75} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-medium text-ink">{meta.label}</span>
                        {rec.file_name && <span className="truncate text-[13px] text-sub">{rec.file_name}</span>}
                      </div>
                      <div className="truncate text-[12px] text-faint">{excerpt(rec.reason)}</div>
                    </div>
                    <Badge tone={RISK_TONE[rec.risk]} className="hidden sm:inline-flex">{rec.risk}</Badge>
                    <span className="mono w-20 shrink-0 text-right text-[13px] text-ok-ink">
                      {rec.estimated_saving_bytes ? formatBytes(rec.estimated_saving_bytes) : <span className="text-faint">review</span>}
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-faint" />
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </Card>

      <Card title="Recent actions" action={<Link to="/history" className="text-[12px] font-medium text-accent-ink hover:underline">History & Restore →</Link>} bodyClassName="p-0">
        {history.length === 0 ? (
          <p className="px-4 py-6 text-center text-[13px] text-faint">No actions yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="border-b border-line">
                <tr>
                  <th className="th">File</th><th className="th">Action</th><th className="th text-right">Before</th>
                  <th className="th text-right">After</th><th className="th text-right">Saved</th><th className="th">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {history.map((h) => (
                  <tr key={h.id}>
                    <td className="td max-w-[260px] truncate font-medium">{h.file_name}</td>
                    <td className="td text-sub">{h.action.replace(/_/g, " ")}</td>
                    <td className="td mono text-right text-sub">{formatBytes(h.original_size_bytes)}</td>
                    <td className="td mono text-right text-sub">{formatBytes(h.new_size_bytes)}</td>
                    <td className="td mono text-right text-ok-ink">{formatBytes(h.saved_bytes)}</td>
                    <td className="td text-faint">{formatDate(h.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={!!archiving}
        title={archiving ? `Archive ${archiving.length} files into one ZIP?` : ""}
        description={archiving ? `${formatBytes(archiving.reduce((s, f) => s + f.size_bytes, 0))} in total. The ZIP is uploaded and verified before any original is touched.` : ""}
        consequences={[
          { kind: "undoable", text: "Originals move to Drive's Trash — restore each from History & Restore." },
          { kind: "permanent", text: "Google empties Drive's Trash after 30 days; after that only the ZIP remains." },
          { kind: "info", text: "Links and sharing of the originals don't carry over to the ZIP." },
        ]}
        confirmLabel="Archive"
        busy={busy}
        onConfirm={archive}
        onCancel={() => setArchiving(null)}
      />
    </div>
  );
}

/** Semicircular gauge drawn as an SVG arc. */
function ScoreGauge({ score }) {
  const r = 44;
  const half = Math.PI * r;
  const tone = score >= 85 ? "stroke-ok" : score >= 60 ? "stroke-warn" : "stroke-bad";
  return (
    <div className="relative h-[64px] w-[112px] shrink-0">
      <svg viewBox="0 0 112 64" className="h-full w-full" aria-label={`Optimization score ${score} of 100`}>
        <path d="M 12 56 A 44 44 0 0 1 100 56" fill="none" className="stroke-track" strokeWidth="8" />
        <path d="M 12 56 A 44 44 0 0 1 100 56" fill="none" className={tone} strokeWidth="8" strokeDasharray={`${(score / 100) * half} ${half}`} />
      </svg>
      <div className="absolute inset-x-0 bottom-0 text-center">
        <span className="mono text-[22px] font-medium leading-none text-ink">{score}</span>
        <span className="mono text-[11px] text-faint">/100</span>
      </div>
    </div>
  );
}
