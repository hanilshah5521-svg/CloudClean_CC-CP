import { useEffect, useState } from "react";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import Card from "../components/Card.jsx";
import { Loading, EmptyState } from "../components/Loading.jsx";
import { formatBytes, formatDate } from "../utils/format.js";

const STATUS_STYLE = { success: "bg-emerald-50 text-emerald-700", skipped: "bg-slate-100 text-slate-500", failed: "bg-red-50 text-red-700", reverted: "bg-amber-50 text-amber-700" };

export default function History() {
  const [loading, setLoading] = useState(true);
  const [history, setHistory] = useState([]);
  const [restoring, setRestoring] = useState(null);
  const toast = useToast();

  async function load() {
    setHistory(await api.getHistory());
  }

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, []);

  async function restore(id) {
    setRestoring(id);
    try {
      await api.restoreAction(id);
      toast("File restored from Trash.");
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setRestoring(null);
    }
  }

  if (loading) return <Loading label="Loading history…" />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Action History</h1>
        <p className="text-sm text-slate-500">Every optimization CloudClean has performed, persisted so nothing is a mystery later.</p>
      </div>

      <Card>
        {history.length === 0 ? (
          <EmptyState title="No actions yet" subtitle="Compress, archive, or trash a duplicate to see it appear here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-400 uppercase tracking-wide">
                  <th className="py-2 pr-4">File</th>
                  <th className="py-2 pr-4">Action</th>
                  <th className="py-2 pr-4">Original</th>
                  <th className="py-2 pr-4">New</th>
                  <th className="py-2 pr-4">Saved</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">When</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="border-t border-slate-100">
                    <td className="py-2 pr-4 max-w-[220px] truncate font-medium text-slate-800">{h.file_name}</td>
                    <td className="py-2 pr-4 capitalize text-slate-600">{h.action}</td>
                    <td className="py-2 pr-4 text-slate-500">{formatBytes(h.original_size_bytes)}</td>
                    <td className="py-2 pr-4 text-slate-500">{formatBytes(h.new_size_bytes)}</td>
                    <td className="py-2 pr-4 font-medium text-emerald-700">{formatBytes(h.saved_bytes)}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLE[h.status] || ""}`}>{h.status}</span>
                    </td>
                    <td className="py-2 pr-4 text-slate-400">{formatDate(h.created_at)}</td>
                    <td className="py-2">
                      {h.action === "trashed" && h.status === "success" && (
                        <button onClick={() => restore(h.id)} disabled={restoring === h.id} className="text-brand-600 text-xs font-semibold hover:underline disabled:opacity-50">
                          {restoring === h.id ? "Restoring…" : "Restore"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
