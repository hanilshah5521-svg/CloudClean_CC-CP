import Card from "./Card.jsx";
import { formatBytes } from "../utils/format.js";

export default function StorageOverviewCard({ storage }) {
  if (!storage) return null;
  const usedPct = Math.min(100, storage.used_percent);
  const projectedPct = Math.min(100, storage.projected_used_percent);
  const barColor = usedPct >= 90 ? "bg-red-500" : usedPct >= 75 ? "bg-amber-500" : "bg-brand-600";

  return (
    <Card title="Google Drive Storage" subtitle="Live snapshot from your most recent analysis">
      <div className="flex items-end justify-between mb-3">
        <div>
          <div className="text-3xl font-bold text-slate-900">
            {formatBytes(storage.used_bytes)} <span className="text-lg font-medium text-slate-400">/ {formatBytes(storage.quota_bytes)}</span>
          </div>
          <div className="text-sm text-slate-500 mt-1">{usedPct}% used</div>
        </div>
        <div className="text-right">
          <div className="text-sm text-slate-500">Remaining</div>
          <div className="text-lg font-semibold text-slate-800">{formatBytes(storage.remaining_bytes)}</div>
        </div>
      </div>

      <div className="relative h-3 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full ${barColor} transition-all`} style={{ width: `${usedPct}%` }} />
        <div
          className="absolute top-0 h-full border-r-2 border-dashed border-emerald-500"
          style={{ width: `${projectedPct}%` }}
          title="Projected usage after optimization"
        />
      </div>

      <div className="grid grid-cols-2 gap-4 mt-5">
        <div className="rounded-xl bg-emerald-50 p-4">
          <div className="text-xs font-medium text-emerald-700 uppercase tracking-wide">Potentially Recoverable</div>
          <div className="text-xl font-bold text-emerald-800 mt-1">{formatBytes(storage.recoverable_bytes)}</div>
        </div>
        <div className="rounded-xl bg-slate-50 p-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">After Optimization</div>
          <div className="text-xl font-bold text-slate-800 mt-1">
            {formatBytes(storage.projected_used_bytes)} <span className="text-sm font-normal text-slate-400">({storage.projected_used_percent}%)</span>
          </div>
        </div>
      </div>
    </Card>
  );
}
