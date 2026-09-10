import { useEffect, useState } from "react";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import Card from "../components/Card.jsx";
import { Loading, EmptyState } from "../components/Loading.jsx";
import { formatBytes } from "../utils/format.js";

const CONFIDENCE_STYLE = { High: "bg-emerald-50 text-emerald-700", Medium: "bg-amber-50 text-amber-700", Low: "bg-slate-100 text-slate-600" };

export default function Compression() {
  const [loading, setLoading] = useState(true);
  const [candidates, setCandidates] = useState([]);
  const [working, setWorking] = useState(null);
  const [results, setResults] = useState({});
  const toast = useToast();

  async function load() {
    setCandidates(await api.getCompressionCandidates());
  }

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, []);

  async function compress(fileId) {
    setWorking(fileId);
    try {
      const res = await api.compressFile(fileId);
      setResults((prev) => ({ ...prev, [fileId]: res }));
      if (res.success) {
        toast(`Compressed successfully — saved ${formatBytes(res.saved_bytes)} (${res.reduction_percent}%).`);
      } else {
        toast(res.message, "error");
      }
      setCandidates((prev) => prev.filter((c) => c.file_id !== fileId));
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setWorking(null);
    }
  }

  if (loading) return <Loading label="Loading compression candidates…" />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Compression</h1>
        <p className="text-sm text-slate-500">Real, on-demand compression — the original is only replaced after the optimized copy is uploaded and verified.</p>
      </div>

      {candidates.length === 0 ? (
        <Card><EmptyState title="No compression candidates" subtitle="Nothing meets the minimum-saving threshold right now, or you haven't analyzed yet." /></Card>
      ) : (
        <div className="space-y-4">
          {candidates.map((c) => (
            <Card key={c.file_id}>
              <div className="flex items-start justify-between gap-6 flex-wrap">
                <div className="min-w-0">
                  <h3 className="font-semibold text-slate-900 truncate">{c.name}</h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CONFIDENCE_STYLE[c.confidence_label]}`}>
                      {c.confidence_label} confidence
                    </span>
                    <span className="text-xs text-slate-400">Method: {c.method}</span>
                  </div>
                  <div className="grid grid-cols-3 gap-6 mt-4 text-sm">
                    <div>
                      <div className="text-xs text-slate-400">Current</div>
                      <div className="font-semibold text-slate-800">{formatBytes(c.current_size_bytes)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-400">Estimated</div>
                      <div className="font-semibold text-slate-800">{formatBytes(c.estimated_optimized_size_bytes)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-400">Potential saving</div>
                      <div className="font-semibold text-emerald-700">{formatBytes(c.estimated_saving_bytes)}</div>
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => compress(c.file_id)}
                  disabled={working === c.file_id}
                  className="px-5 py-2.5 rounded-xl bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700 disabled:opacity-60 shrink-0"
                >
                  {working === c.file_id ? "Compressing…" : "Compress Now"}
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
