import { useEffect, useState } from "react";
import {
  ResponsiveContainer, PieChart, Pie, Cell, Tooltip, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, LineChart, Line, Legend,
} from "recharts";
import { api } from "../services/api.js";
import Card from "../components/Card.jsx";
import { Loading, EmptyState } from "../components/Loading.jsx";
import { formatBytes, formatDate } from "../utils/format.js";

const COLORS = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#64748b"];
const RANGES = [{ value: "7d", label: "7 days" }, { value: "30d", label: "30 days" }, { value: "90d", label: "90 days" }, { value: "all", label: "All time" }];

export default function Analytics() {
  const [loading, setLoading] = useState(true);
  const [breakdown, setBreakdown] = useState(null);
  const [history, setHistory] = useState(null);
  const [storage, setStorage] = useState(null);
  const [range, setRange] = useState("30d");

  useEffect(() => {
    Promise.all([api.getBreakdown(), api.getStorageHistory(range), api.getStorage()]).then(([b, h, s]) => {
      setBreakdown(b);
      setHistory(h);
      setStorage(s);
      setLoading(false);
    });
  }, [range]);

  if (loading) return <Loading label="Loading analytics…" />;

  const categoryData = breakdown.by_category.map((c) => ({ name: c.category, value: c.size_bytes, count: c.count }));
  const inactiveData = Object.entries(breakdown.inactive_by_bucket).map(([bucket, bytes]) => ({ bucket, bytes: bytes / (1024 ** 2) }));
  const largestData = breakdown.largest_files.map((f) => ({ name: f.name.length > 18 ? f.name.slice(0, 16) + "…" : f.name, mb: f.size_bytes / (1024 ** 2) }));
  const historyData = (history.points || []).map((p) => ({
    date: new Date(p.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    "Used (GB)": +(p.used_bytes / 1024 ** 3).toFixed(2),
    "Recoverable (GB)": +(p.recoverable_bytes / 1024 ** 3).toFixed(2),
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Analytics</h1>
          <p className="text-sm text-slate-500">Every chart here is built from real analysis runs — nothing is fabricated.</p>
        </div>
        <select value={range} onChange={(e) => setRange(e.target.value)} className="px-3 py-2 rounded-lg border border-slate-200 text-sm">
          {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
      </div>

      <Card title="Storage Usage Over Time" subtitle="Recorded at each analysis run">
        {history.insufficient_history ? (
          <EmptyState title="Not enough history yet" subtitle="Run at least two analyses over time to see a trend here." />
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={historyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="Used (GB)" stroke="#2563eb" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="Recoverable (GB)" stroke="#10b981" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Storage by File Type">
          {categoryData.length === 0 ? <EmptyState title="No data" /> : (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={categoryData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={(d) => d.name}>
                  {categoryData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v) => formatBytes(v)} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Largest Files">
          {largestData.length === 0 ? <EmptyState title="No data" /> : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={largestData} layout="vertical" margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis type="number" tick={{ fontSize: 12 }} unit=" MB" />
                <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => `${v.toFixed(1)} MB`} />
                <Bar dataKey="mb" fill="#2563eb" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Potentially Inactive Storage" subtitle="By how long the file has gone unmodified">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={inactiveData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 12 }} unit=" MB" />
              <Tooltip formatter={(v) => `${v.toFixed(0)} MB`} />
              <Bar dataKey="bytes" fill="#f59e0b" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Recovery Opportunity" subtitle="Duplicate storage vs. compressible storage">
          <div className="space-y-4 py-4">
            <Opportunity label="Duplicate storage" bytes={breakdown.duplicate_storage_bytes} total={storage.used_bytes} color="bg-amber-500" />
            <Opportunity label="Compressible storage" bytes={breakdown.compressible_storage_bytes} total={storage.used_bytes} color="bg-brand-600" />
          </div>
        </Card>
      </div>
    </div>
  );
}

function Opportunity({ label, bytes, total, color }) {
  const pct = total > 0 ? Math.min(100, (bytes / total) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-slate-600">{label}</span>
        <span className="font-semibold text-slate-800">{formatBytes(bytes)} ({pct.toFixed(1)}%)</span>
      </div>
      <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
