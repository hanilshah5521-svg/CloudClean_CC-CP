import { useEffect, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartColumn } from "lucide-react";
import { api } from "../services/api.js";
import { useScan } from "../context/scan.jsx";
import { useTheme } from "../context/theme.jsx";
import { DriveTrashNotice } from "../components/GoogleLinks.jsx";
import { Card, EmptyState, FilterPills, PageHeader, SkeletonRows, Stat } from "../components/ui/primitives.jsx";
import { formatBytes, formatDate } from "../utils/format.js";

const RANGES = [{ value: "7d", label: "7 days" }, { value: "30d", label: "30 days" }, { value: "90d", label: "90 days" }, { value: "all", label: "All time" }];
const BUCKETS = ["30+ days", "90+ days", "180+ days", "1+ year", "2+ years"];
const GB = 1024 ** 3;
const MB = 1024 ** 2;

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
  const [data, setData] = useState(null);
  const { version } = useScan();
  const { colors: c } = useTheme();

  useEffect(() => {
    Promise.all([api.getBreakdown(), api.getStorageHistory(range), api.getStorage()]).then(
      ([breakdown, history, storage]) => setData({ breakdown, history, storage }),
      () => setData({ error: true }),
    );
  }, [range, version]);

  if (!data) return <Card bodyClassName="p-0"><SkeletonRows rows={8} /></Card>;
  if (data.error) return <Card><EmptyState icon={ChartColumn} title="Analytics unavailable" subtitle="Run a scan first." /></Card>;
  const { breakdown, history, storage } = data;

  const byType = [...breakdown.by_category].sort((a, b) => b.size_bytes - a.size_bytes).map((c) => ({ name: c.category, GB: c.size_bytes / GB, count: c.count }));
  const largest = breakdown.largest_files.map((f) => ({ name: f.name.length > 22 ? `${f.name.slice(0, 20)}…` : f.name, MB: f.size_bytes / MB }));
  const inactive = BUCKETS.map((b) => ({ name: b, GB: (breakdown.inactive_by_bucket[b] || 0) / GB }));
  const trend = (history.points || []).map((p) => ({ date: formatDate(p.date), Used: p.used_bytes / GB, Recoverable: p.recoverable_bytes / GB }));
  const AXIS = { fontFamily: "JetBrains Mono", fontSize: 11, fill: c.faint };
  const LABEL = { ...AXIS, fill: c.sub };
  const oldBytes = (breakdown.inactive_by_bucket["1+ year"] || 0) + (breakdown.inactive_by_bucket["2+ years"] || 0);

  return (
    <div className="space-y-4">
      <PageHeader title="Analytics" description="Built from your analysis runs — nothing here is estimated beyond what each label says." />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Duplicate copies" value={formatBytes(breakdown.duplicate_storage_bytes)} />
        <Stat label="Est. compressible" value={formatBytes(breakdown.compressible_storage_bytes)} />
        <Stat label="Not modified 1+ year" value={formatBytes(oldBytes)} />
        <Stat label="In Drive Trash" value={formatBytes(storage.drive_trash_bytes)} tone={storage.drive_trash_bytes ? "warn" : undefined} sub="auto-emptied after 30 days" />
      </div>

      {storage.drive_trash_bytes > 0 && (
        <DriveTrashNotice>
          <span className="mono">{formatBytes(storage.drive_trash_bytes)}</span> in Drive&apos;s Trash still counts toward your quota. Google deletes each item 30
          days after it was trashed; emptying the Trash in Drive frees it sooner.
        </DriveTrashNotice>
      )}

      <Card title="Storage over time" subtitle="Recorded at each analysis run" action={<FilterPills options={RANGES} value={range} onChange={setRange} />}>
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
