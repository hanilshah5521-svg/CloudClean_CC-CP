import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../services/api.js";
import { useToast } from "../hooks/useToast.jsx";
import Card from "../components/Card.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import { Loading, EmptyState } from "../components/Loading.jsx";
import { formatBytes, formatDate, monthsAgo } from "../utils/format.js";

const FILTERS = [
  { value: "", label: "All files" },
  { value: "large", label: "Large" },
  { value: "duplicate", label: "Duplicate" },
  { value: "compressible", label: "Compressible" },
  { value: "inactive", label: "Inactive" },
  { value: "archive_candidate", label: "Archive candidate" },
  { value: "optimized", label: "Already optimized" },
];

const REC_BADGE = {
  compress: "bg-brand-50 text-brand-700", duplicate: "bg-amber-50 text-amber-700",
  archive: "bg-purple-50 text-purple-700", already_optimized: "bg-emerald-50 text-emerald-700",
  keep: "bg-slate-100 text-slate-500",
};

export default function FileExplorer() {
  const [params, setParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({ files: [], total: 0 });
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("size");
  const [order, setOrder] = useState("desc");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(new Set());
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const filter = params.get("filter") || "";

  async function load() {
    setLoading(true);
    const res = await api.getFiles({ search, filter, sort, order, page, page_size: 25 });
    setData(res);
    setLoading(false);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, sort, order, page]);

  function toggleSelect(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const selectedFiles = data.files.filter((f) => selected.has(f.id));
  const selectedTotal = selectedFiles.reduce((s, f) => s + f.size_bytes, 0);

  async function doArchive() {
    setBusy(true);
    try {
      const res = await api.archiveFiles(Array.from(selected), `cloudclean_archive_${Date.now()}.zip`);
      toast(`Archived ${selectedFiles.length} files — saved ${formatBytes(res.saved_bytes)}.`);
      setSelected(new Set());
      setConfirmArchive(false);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function quickCompress(fileId) {
    try {
      const res = await api.compressFile(fileId);
      toast(res.success ? `Saved ${formatBytes(res.saved_bytes)}.` : res.message, res.success ? "success" : "error");
      await load();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">File Explorer</h1>
        <p className="text-sm text-slate-500">Search, filter, and take action on individual files.</p>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (setPage(1), load())}
            placeholder="Search files by name…"
            className="flex-1 min-w-[200px] px-3 py-2 rounded-lg border border-slate-200 text-sm"
          />
          <select
            value={filter}
            onChange={(e) => { setParams(e.target.value ? { filter: e.target.value } : {}); setPage(1); }}
            className="px-3 py-2 rounded-lg border border-slate-200 text-sm"
          >
            {FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value)} className="px-3 py-2 rounded-lg border border-slate-200 text-sm">
            <option value="size">Sort: Size</option>
            <option value="modified">Sort: Modified</option>
            <option value="savings">Sort: Potential savings</option>
            <option value="name">Sort: Name</option>
          </select>
          <button onClick={() => setOrder(order === "desc" ? "asc" : "desc")} className="px-3 py-2 rounded-lg border border-slate-200 text-sm">
            {order === "desc" ? "↓ Desc" : "↑ Asc"}
          </button>
        </div>

        {selected.size > 0 && (
          <div className="flex items-center justify-between bg-brand-50 rounded-xl px-4 py-3 mb-4">
            <span className="text-sm font-medium text-brand-800">
              {selected.size} file{selected.size === 1 ? "" : "s"} selected · {formatBytes(selectedTotal)}
            </span>
            <button onClick={() => setConfirmArchive(true)} className="px-4 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700">
              Archive Selected
            </button>
          </div>
        )}

        {loading ? <Loading /> : data.files.length === 0 ? (
          <EmptyState title="No files match" subtitle="Try a different filter or search term." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-400 uppercase tracking-wide">
                  <th className="py-2 pr-2"><input type="checkbox" onChange={(e) => setSelected(e.target.checked ? new Set(data.files.map((f) => f.id)) : new Set())} /></th>
                  <th className="py-2 pr-4">Name</th>
                  <th className="py-2 pr-4">Type</th>
                  <th className="py-2 pr-4">Size</th>
                  <th className="py-2 pr-4">Modified</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Potential Saving</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {data.files.map((f) => (
                  <tr key={f.id} className="border-t border-slate-100">
                    <td className="py-2 pr-2"><input type="checkbox" checked={selected.has(f.id)} onChange={() => toggleSelect(f.id)} /></td>
                    <td className="py-2 pr-4 max-w-[240px] truncate font-medium text-slate-800">{f.name}</td>
                    <td className="py-2 pr-4 text-slate-500">{f.category}</td>
                    <td className="py-2 pr-4 text-slate-600">{formatBytes(f.size_bytes)}</td>
                    <td className="py-2 pr-4 text-slate-400">{formatDate(f.modified_time)} <span className="text-xs">({monthsAgo(f.inactivity_days)})</span></td>
                    <td className="py-2 pr-4">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${REC_BADGE[f.recommendation_type] || REC_BADGE.keep}`}>
                        {f.recommendation_type.replace("_", " ")}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-emerald-700 font-medium">{f.estimated_savings_bytes ? formatBytes(f.estimated_savings_bytes) : "—"}</td>
                    <td className="py-2">
                      {f.recommendation_type === "compress" && (
                        <button onClick={() => quickCompress(f.id)} className="text-brand-600 text-xs font-semibold hover:underline">Compress</button>
                      )}
                      {f.duplicate_group_id && <span className="text-amber-600 text-xs font-semibold">See Duplicates</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-between mt-4 text-sm text-slate-500">
          <span>{data.total} total files</span>
          <div className="flex gap-2">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="px-3 py-1 rounded-lg border border-slate-200 disabled:opacity-40">Prev</button>
            <span className="px-2 py-1">Page {page}</span>
            <button disabled={page * 25 >= data.total} onClick={() => setPage((p) => p + 1)} className="px-3 py-1 rounded-lg border border-slate-200 disabled:opacity-40">Next</button>
          </div>
        </div>
      </Card>

      <ConfirmDialog
        open={confirmArchive}
        title="Archive selected files?"
        body={`${selected.size} file(s), ${formatBytes(selectedTotal)} total, will be bundled into a ZIP and uploaded to Drive. Originals are only moved to Trash after the archive upload is verified.`}
        confirmLabel="Archive"
        busy={busy}
        onConfirm={doArchive}
        onCancel={() => setConfirmArchive(false)}
      />
    </div>
  );
}
