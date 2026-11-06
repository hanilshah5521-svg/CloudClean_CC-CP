import { useEffect, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartColumn, PiggyBank } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../services/api.js";
import { accountTone, useAccounts } from "../context/accounts.jsx";
import { useScan } from "../context/scan.jsx";
import { useTheme } from "../context/theme.jsx";
import { DriveTrashNotice } from "../components/GoogleLinks.jsx";
import { Badge, Card, EmptyState, FilterPills, PageHeader, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
import { formatBytes, formatDate } from "../utils/format.js";

const RANGES = [{ value: "7d", label: "7 days" }, { value: "30d", label: "30 days" }, { value: "90d", label: "90 days" }, { value: "all", label: "All time" }];
const BUCKETS = ["30+ days", "90+ days", "180+ days", "1+ year", "2+ years"];
const GB = 1024 ** 3;
const MB = 1024 ** 2;
// History action types, grouped the way people think of them.
const SAVED_KINDS = [
  { label: "Compression", actions: ["compressed"] },
  { label: "Moved to Trash", actions: ["trashed", "gmail_trashed"], sub: "duplicates & files; freed once Trash empties" },
  { label: "Archived into ZIPs", actions: ["archive_created", "archived"] },
];

function ChartTip({ active, payload, label, unit = "GB" }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-line bg-surface px-2.5 py-1.5 text-[12px] shadow-[0_4px_16px_rgb(var(--shade)/0.08)]">
      <div className="mb-0.5 text-sub">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="mono text-ink">
          {p.name}: {p.value.toFixed(2)} {unit}
        </div>
      ))}
    </div>
  );
}

export default function Analytics() {
  const [range, setRange] = useState("30d");
  const [filter, setFilter] = useState(""); // account id, "" = every linked account
  const [data, setData] = useState(null);
  const { version } = useScan();
  const { accounts, multiple } = useAccounts();
  const { colors: c } = useTheme();

  useEffect(() => {
    const accountId = filter || undefined;
    Promise.all([api.getBreakdown(accountId), api.getStorageHistory(range, accountId), api.getHistorySummary(accountId)]).then(
      ([breakdown, history, saved]) => setData({ breakdown, history, saved }),
      () => setData({ error: true }),
    );
  }, [range, filter, version]);

  if (!data) return <Card bodyClassName="p-0"><SkeletonRows rows={8} /></Card>;
  if (data.error) return <Card><EmptyState icon={ChartColumn} title="Analytics unavailable" subtitle="Run a scan first." /></Card>;
  const { breakdown, history, saved } = data;
  const savedBy = (actions) => actions.reduce((n, a) => n + (saved.by_action[a]?.saved_bytes || 0), 0);
  const countBy = (actions) => actions.reduce((n, a) => n + (saved.by_action[a]?.count || 0), 0);
  const savedTrend = saved.timeline.map((p) => ({ date: formatDate(p.date), Saved: p.cumulative_bytes / GB }));
  const trashBytes = breakdown.drive_trash_bytes || 0;

  const byType = [...breakdown.by_category].sort((a, b) => b.size_bytes - a.size_bytes).map((c) => ({ name: c.category, GB: c.size_bytes / GB, count: c.count }));
  const largest = breakdown.largest_files.map((f) => ({ name: f.name.length > 22 ? `${f.name.slice(0, 20)}…` : f.name, MB: f.size_bytes / MB }));
  const inactive = BUCKETS.map((b) => ({ name: b, GB: (breakdown.inactive_by_bucket[b] || 0) / GB }));
  const trend = (history.points || []).map((p) => ({ date: formatDate(p.date), Used: p.used_bytes / GB, Recoverable: p.recoverable_bytes / GB }));
  const AXIS = { fontFamily: "JetBrains Mono", fontSize: 11, fill: c.faint };
  const LABEL = { ...AXIS, fill: c.sub };
  const oldBytes = (breakdown.inactive_by_bucket["1+ year"] || 0) + (breakdown.inactive_by_bucket["2+ years"] || 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Analytics"
        description={`Built from your scans and History — nothing here is estimated beyond what each label says. Everything is kept in CloudClean's database, so it stays after restarts.${multiple ? " Shows all linked accounts together, or pick one." : ""}`}
      />

      {multiple && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] text-faint">Show</span>
          <FilterPills
            options={[{ value: "", label: "All accounts" }, ...accounts.map((a) => ({ value: String(a.id), label: a.email.split("@")[0] }))]}
            value={filter}
            onChange={setFilter}
          />
        </div>
      )}

      <Card
        title="Saved by CloudClean"
        subtitle={saved.first_action_at ? `All time, since ${formatDate(saved.first_action_at)} · from History, undone actions excluded` : "From History: every compression, trash and archive that's still in effect"}
        action={<Link to="/history" className="text-[12px] font-medium text-accent-ink hover:underline">History & Restore →</Link>}
      >
        {saved.actions === 0 ? (
          <EmptyState icon={PiggyBank} title="Nothing saved yet" subtitle="Compress, archive or trash something and the space it saves is counted here — for good." />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Total saved" value={formatBytes(saved.saved_bytes)} tone="ok" sub={`${saved.actions} action${saved.actions === 1 ? "" : "s"} recorded`} />
              {SAVED_KINDS.map((k) => (
                <Stat key={k.label} label={k.label} value={formatBytes(savedBy(k.actions))}
                      sub={k.sub ? `${countBy(k.actions)} · ${k.sub}` : `${countBy(k.actions)} file${countBy(k.actions) === 1 ? "" : "s"}`} />
              ))}
            </div>
            {savedTrend.length > 1 && (
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={savedTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={c.track} vertical={false} />
                  <XAxis dataKey="date" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44} unit=" GB" />
                  <Tooltip content={<ChartTip />} />
                  <Area type="stepAfter" dataKey="Saved" name="Saved so far" stroke={c.ok} fill={c.ok} fillOpacity={0.1} strokeWidth={1.5} />
                </AreaChart>
              </ResponsiveContainer>
            )}
            {multiple && !filter && (
              <ul className="divide-y divide-line rounded border border-line">
                {saved.by_account.map((a) => (
                  <li key={a.account_id} className="flex items-center justify-between gap-3 px-3 py-2 text-[13px]">
                    <span className="flex min-w-0 items-center gap-2">
                      <Badge tone={accountTone(accounts, a.account_id)}>{a.account_email.split("@")[0]}</Badge>
                      <span className="truncate text-sub">{a.account_email}</span>
                    </span>
                    <span className="text-sub">
                      <span className="mono text-ok-ink">{formatBytes(a.saved_bytes)}</span> · {a.actions} action{a.actions === 1 ? "" : "s"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Duplicate copies" value={formatBytes(breakdown.duplicate_storage_bytes)} />
        <Stat label="Est. compressible" value={formatBytes(breakdown.compressible_storage_bytes)} />
        <Stat label="Not modified 1+ year" value={formatBytes(oldBytes)} />
        <Stat label="In Drive Trash" value={formatBytes(trashBytes)} tone={trashBytes ? "warn" : undefined} sub="auto-emptied after 30 days" />
      </div>

      {trashBytes > 0 && (
        <DriveTrashNotice>
          <span className="mono">{formatBytes(trashBytes)}</span> in Drive&apos;s Trash still counts toward your quota. Google deletes each item 30
          days after it was trashed; emptying the Trash in Drive frees it sooner.
        </DriveTrashNotice>
      )}

      <Card title="Storage over time" subtitle={multiple && !filter ? "Recorded at each scan · all accounts added up" : "Recorded at each scan"} action={<FilterPills options={RANGES} value={range} onChange={setRange} />}>
        {history.insufficient_history ? (
          <EmptyState title="Not enough history yet" subtitle="Run at least two scans over time to see a trend." />
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={c.track} vertical={false} />
              <XAxis dataKey="date" tick={AXIS} axisLine={false} tickLine={false} />
              <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44} unit=" GB" />
              <Tooltip content={<ChartTip />} />
              <Area type="monotone" dataKey="Used" stroke={c.tierDrive} fill={c.tierDrive} fillOpacity={0.08} strokeWidth={1.5} />
              <Area type="monotone" dataKey="Recoverable" stroke={c.ok} fill={c.ok} fillOpacity={0.08} strokeWidth={1.5} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Size by file type">
          <ResponsiveContainer width="100%" height={Math.max(160, byType.length * 30)}>
            <BarChart data={byType} layout="vertical" margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={c.track} horizontal={false} />
              <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} unit=" GB" />
              <YAxis type="category" dataKey="name" tick={LABEL} axisLine={false} tickLine={false} width={96} />
              <Tooltip content={<ChartTip />} cursor={{ fill: c.canvas }} />
              <Bar dataKey="GB" name="Size" fill={c.tierDrive} barSize={14} radius={[0, 2, 2, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Inactive data" subtitle="By time since last modified">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={inactive} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={c.track} vertical={false} />
              <XAxis dataKey="name" tick={AXIS} axisLine={false} tickLine={false} />
              <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44} unit=" GB" />
              <Tooltip content={<ChartTip />} cursor={{ fill: c.canvas }} />
              <Bar dataKey="GB" name="Size" fill={c.warn} barSize={28} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card title="Largest files">
        <ResponsiveContainer width="100%" height={Math.max(160, largest.length * 28)}>
          <BarChart data={largest} layout="vertical" margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={c.track} horizontal={false} />
            <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} unit=" MB" />
            <YAxis type="category" dataKey="name" tick={LABEL} axisLine={false} tickLine={false} width={170} />
            <Tooltip content={<ChartTip unit="MB" />} cursor={{ fill: c.canvas }} />
            <Bar dataKey="MB" name="Size" fill={c.sub} barSize={12} radius={[0, 2, 2, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}
