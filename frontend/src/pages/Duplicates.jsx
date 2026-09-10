import { useEffect, useState } from "react";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import Card from "../components/Card.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import { Loading, EmptyState } from "../components/Loading.jsx";
import { formatBytes, formatDate } from "../utils/format.js";

const LEVEL_LABEL = { hash: "Content match (exact)", size_name: "Size + name match", name: "Name match" };

export default function Duplicates() {
  const [loading, setLoading] = useState(true);
  const [groups, setGroups] = useState([]);
  const [keepChoice, setKeepChoice] = useState({});
  const [confirmGroup, setConfirmGroup] = useState(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function load() {
    const data = await api.getDuplicates();
    setGroups(data);
    setKeepChoice((prev) => {
      const next = { ...prev };
      for (const g of data) if (!(g.id in next)) next[g.id] = g.recommended_keep_drive_id;
      return next;
    });
  }

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, []);

  async function confirmTrash() {
    setBusy(true);
    try {
      const group = confirmGroup;
      const keep = keepChoice[group.id];
      const res = await api.trashDuplicates(group.id, keep);
      const recovered = res.trashed.reduce((sum, r) => sum + r.saved_bytes, 0);
      toast(`Moved ${res.trashed.length} file(s) to Trash — recovered ${formatBytes(recovered)}.`);
      setConfirmGroup(null);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading label="Loading duplicates…" />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Duplicate Files</h1>
        <p className="text-sm text-slate-500">Review each group before anything moves to Trash — nothing here is automatic.</p>
      </div>

      {groups.length === 0 ? (
        <Card><EmptyState title="No duplicate groups found" subtitle="Run an analysis from the Dashboard if you haven't recently." /></Card>
      ) : (
        <div className="space-y-4">
          {groups.map((g) => {
            const keep = keepChoice[g.id];
            const removable = g.files.filter((f) => f.drive_id !== keep);
            const recovery = removable.reduce((s, f) => s + f.size_bytes, 0);
            return (
              <Card key={g.id}>
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                      Duplicate Group #{g.id} · {LEVEL_LABEL[g.match_level] || g.match_level}
                    </span>
                    <p className="text-sm text-slate-500">{g.files.length} files found</p>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-slate-400">Potential recovery</div>
                    <div className="text-lg font-bold text-emerald-700">{formatBytes(recovery)}</div>
                  </div>
                </div>

                <div className="divide-y divide-slate-100 border border-slate-100 rounded-xl overflow-hidden">
                  {g.files.map((f) => (
                    <label key={f.drive_id} className={`flex items-center gap-3 px-4 py-3 cursor-pointer ${keep === f.drive_id ? "bg-emerald-50" : ""}`}>
                      <input
                        type="radio"
                        name={`keep-${g.id}`}
                        checked={keep === f.drive_id}
                        onChange={() => setKeepChoice((prev) => ({ ...prev, [g.id]: f.drive_id }))}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-slate-800 truncate">{f.name}</div>
                        <div className="text-xs text-slate-400">Modified {formatDate(f.modified_time)}</div>
                      </div>
                      <div className="text-sm text-slate-600">{formatBytes(f.size_bytes)}</div>
                      {keep === f.drive_id && (
                        <span className="text-xs font-semibold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full">Keep</span>
                      )}
                    </label>
                  ))}
                </div>

                <div className="flex justify-end mt-4">
                  <button
                    onClick={() => setConfirmGroup(g)}
                    className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700"
                  >
                    Move {removable.length} duplicate{removable.length === 1 ? "" : "s"} to Trash
                  </button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={!!confirmGroup}
        title="Move duplicates to Trash?"
        body={confirmGroup ? `This will move ${confirmGroup.files.filter((f) => f.drive_id !== keepChoice[confirmGroup.id]).length} file(s) to Google Drive's Trash. They can be restored from History (or Drive's own Trash) afterward — nothing is permanently deleted.` : ""}
        confirmLabel="Move to Trash"
        danger
        busy={busy}
        onConfirm={confirmTrash}
        onCancel={() => setConfirmGroup(null)}
      />
    </div>
  );
}
