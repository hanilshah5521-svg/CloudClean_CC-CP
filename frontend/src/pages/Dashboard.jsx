import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import Card from "../components/Card.jsx";
import StorageOverviewCard from "../components/StorageOverviewCard.jsx";
import OptimizationScoreCard from "../components/OptimizationScoreCard.jsx";
import RecommendationList from "../components/RecommendationList.jsx";
import { Loading, EmptyState } from "../components/Loading.jsx";
import { formatBytes, formatDate } from "../utils/format.js";

const QUICK_ACTIONS = [
  { to: "/duplicates", icon: "🧬", label: "Find Duplicates" },
  { to: "/compression", icon: "🗜️", label: "Compress Large Files" },
  { to: "/files?filter=inactive", icon: "🕘", label: "Review Inactive Files" },
  { to: "/files?filter=archive_candidate", icon: "🗄️", label: "Archive Old Files" },
];

export default function Dashboard() {
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [storage, setStorage] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [recs, setRecs] = useState([]);
  const [history, setHistory] = useState([]);
  const toast = useToast();

  const loadAll = useCallback(async () => {
    const [s, a, r, h] = await Promise.all([
      api.getStorage(), api.getAnalysis(), api.getRecommendations(), api.getHistory(),
    ]);
    setStorage(s);
    setAnalysis(a);
    setRecs(r);
    setHistory(h.slice(0, 5));
  }, []);

  useEffect(() => {
    loadAll().finally(() => setLoading(false));
  }, [loadAll]);

  async function runAnalysis() {
    setAnalyzing(true);
    try {
      await api.analyze();
      await loadAll();
      toast("Analysis complete.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setAnalyzing(false);
    }
  }

  if (loading) return <Loading label="Loading dashboard…" />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-sm text-slate-500">Intelligent Google Drive Storage Optimization</p>
        </div>
        <button
          onClick={runAnalysis}
          disabled={analyzing}
          className="px-4 py-2.5 rounded-xl bg-brand-600 text-white font-semibold text-sm hover:bg-brand-700 disabled:opacity-60"
        >
          {analyzing ? "Analyzing Drive…" : analysis?.analyzed ? "Re-analyze" : "Analyze Drive"}
        </button>
      </div>

      {!analysis?.analyzed ? (
        <Card>
          <EmptyState
            title="No analysis yet"
            subtitle="Click Analyze Drive to scan your Drive's metadata and generate recommendations."
          />
        </Card>
      ) : (
        <>
          <div className="grid lg:grid-cols-2 gap-5">
            <StorageOverviewCard storage={storage} />
            <OptimizationScoreCard score={analysis.optimization_score} summary={scoreSummary(analysis.optimization_score)} breakdown={analysis.score_breakdown} />
          </div>

          <Card title="Quick Actions">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {QUICK_ACTIONS.map((a) => (
                <Link key={a.to} to={a.to} className="flex flex-col items-center gap-2 p-4 rounded-xl border border-slate-100 hover:border-brand-200 hover:bg-brand-50 transition-colors">
                  <span className="text-2xl">{a.icon}</span>
                  <span className="text-xs font-medium text-slate-700 text-center">{a.label}</span>
                </Link>
              ))}
            </div>
          </Card>

          <Card title="Top Recommendations" subtitle={`${recs.length} pending recommendation${recs.length === 1 ? "" : "s"}`}>
            <RecommendationList recommendations={recs} limit={5} />
          </Card>

          <Card title="Recent Optimizations">
            {history.length === 0 ? (
              <p className="text-sm text-slate-400 py-4 text-center">No actions taken yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400 uppercase tracking-wide">
                      <th className="py-2 pr-4">File</th>
                      <th className="py-2 pr-4">Action</th>
                      <th className="py-2 pr-4">Before</th>
                      <th className="py-2 pr-4">After</th>
                      <th className="py-2 pr-4">Saved</th>
                      <th className="py-2">When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.id} className="border-t border-slate-100">
                        <td className="py-2 pr-4 font-medium text-slate-800 max-w-[200px] truncate">{h.file_name}</td>
                        <td className="py-2 pr-4 capitalize text-slate-600">{h.action}</td>
                        <td className="py-2 pr-4 text-slate-500">{formatBytes(h.original_size_bytes)}</td>
                        <td className="py-2 pr-4 text-slate-500">{formatBytes(h.new_size_bytes)}</td>
                        <td className="py-2 pr-4 font-medium text-emerald-700">{formatBytes(h.saved_bytes)}</td>
                        <td className="py-2 text-slate-400">{formatDate(h.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function scoreSummary(score) {
  if (score >= 85) return "Your Drive is well optimized.";
  if (score >= 60) return "Your Drive has some optimization opportunities.";
  return "Your Drive has significant optimization opportunities.";
}
