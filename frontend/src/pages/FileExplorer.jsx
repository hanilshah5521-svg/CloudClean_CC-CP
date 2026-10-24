import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Archive, ArrowDown, ArrowUp, ArrowUpDown, Copy, Film, FolderTree, Search, X } from "lucide-react";
import { api } from "../services/api.js";
import { useScan } from "../context/scan.jsx";
import { useDrawer } from "../context/drawer.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { useGoogleLinks } from "../hooks/useGoogleLinks.js";
import { DriveTrashNotice } from "../components/GoogleLinks.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, FilterPills, PageHeader, SkeletonRows } from "../components/ui/primitives.jsx";
import { Checkbox, Tip } from "../components/ui/controls.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import BatchDock from "../components/shell/BatchDock.jsx";
import { fileDetails, REC_STATUS } from "../components/details.js";
import { formatBytes, formatDate } from "../utils/format.js";

const FILTERS = [
  { value: "", label: "All" },
  { value: "large", label: "Large" },
  { value: "duplicate", label: "Duplicate" },
  { value: "compressible", label: "Compressible" },
  { value: "inactive", label: "Inactive (90+ days)" },
  { value: "archive_candidate", label: "Archive candidate" },
  { value: "optimized", label: "Optimized" },
];
const PAGE_SIZE = 50;

export default function FileExplorer() {
  const [params, setParams] = useSearchParams();
  const filter = params.get("filter") || "";
  const search = params.get("search") || "";
  const [sort, setSort] = useState({ by: "size", order: "desc" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(new Map()); // id -> file
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [archived, setArchived] = useState(null); // last archive: originals now in Drive's Trash
  const { version } = useScan();
  const { open, close } = useDrawer();
  const navigate = useNavigate();
  const toast = useToast();
  const links = useGoogleLinks();

  const load = useCallback(async () => {
    setData(null);
    setData(await api.getFiles({ search, filter, sort: sort.by, order: sort.order, page, page_size: PAGE_SIZE }));
  }, [search, filter, sort, page]);

  useEffect(() => {
    load().catch((e) => {
      toast(e.message, "error");
      setData({ files: [], total: 0 });
    });
  }, [load, version, toast]);

  useEffect(() => setPage(1), [filter, search, sort]);

  function setParam(key, value) {
    const next = new URLSearchParams(params);
    value ? next.set(key, value) : next.delete(key);
    setParams(next);
  }

  function toggleSort(by) {
    setSort((s) => (s.by === by ? { by, order: s.order === "desc" ? "asc" : "desc" } : { by, order: "desc" }));
  }

  function toggle(file) {
    setSelected((prev) => {
      const next = new Map(prev);
      next.has(file.id) ? next.delete(file.id) : next.set(file.id, file);
      return next;
    });
  }

  async function compress(file) {
    const res = await api.compressFile(file.id);
    toast(res.message, res.success ? "success" : "error");
    close();
    await load();
  }

  function openFile(f) {
    const actions = [];
    if (f.recommendation_type === "compress") {
      actions.push(
        f.category === "video"
          ? { label: "Open video queue", variant: "primary", icon: Film, onClick: () => navigate("/compression") }
          : { label: "Compress now", variant: "primary", icon: Film, onClick: () => compress(f) },
      );
    }
    if (f.duplicate_group_id) actions.push({ label: "View duplicate group", icon: Copy, onClick: () => navigate("/duplicates") });
    open(fileDetails(f, actions, links));
  }

  async function archive() {
    setBusy(true);
    try {
      const files = [...selected.values()];
      const res = await api.archiveFiles(files.map((f) => f.id), `cloudclean_archive_${new Date().toISOString().slice(0, 10)}.zip`);
      toast(
        res.failed?.length
          ? `Archive created, but ${res.failed.length} original(s) couldn't be moved to Trash. See History.`
          : `Archived ${files.length} files into ${res.archive_name} — saves ${formatBytes(res.saved_bytes)} once Trash is emptied.`,
        res.failed?.length ? "error" : "success",
      );
      const moved = files.length - (res.failed?.length || 0);
      if (moved > 0) setArchived({ count: moved, bytes: res.saved_bytes });
      setSelected(new Map());
      setConfirming(false);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  const files = data?.files || [];
  const selectable = files.filter((f) => !f.is_google_workspace_file);
  const allChecked = selectable.length > 0 && selectable.every((f) => selected.has(f.id));
  const selectedBytes = [...selected.values()].reduce((s, f) => s + f.size_bytes, 0);

  return (
    <div className="space-y-4">
      <PageHeader title="File Explorer" description="Every file in your Drive that CloudClean analyzed. Select rows to archive them into one ZIP." />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <FilterPills options={FILTERS} value={filter} onChange={(v) => setParam("filter", v)} />
        <form
          role="search"
          className="relative w-full sm:w-64"
          onSubmit={(e) => {
            e.preventDefault();
            setParam("search", new FormData(e.currentTarget).get("q").trim());
          }}
        >
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
          <input key={search} name="q" defaultValue={search} placeholder="Filter by name" aria-label="Filter files by name" className="field pl-8 pr-7" />
          {search && (
            <button type="button" onClick={() => setParam("search", "")} aria-label="Clear search" className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-ink">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </form>
      </div>

      {archived && (
        <DriveTrashNotice>
          Moved <span className="mono">{archived.count}</span> archived original{archived.count === 1 ? "" : "s"} to Drive&apos;s Trash.{" "}
          <span className="mono">{formatBytes(archived.bytes)}</span> still counts against your storage until the Trash is emptied (Google
          does it after 30 days).
        </DriveTrashNotice>
      )}

      <Card bodyClassName="p-0">
        {!data ? (
          <SkeletonRows rows={10} cols={6} />
        ) : files.length === 0 ? (
          <EmptyState icon={FolderTree} title="No files match" subtitle="Try another filter or search, or run a scan first." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="border-b border-line">
                <tr>
                  <th className="th w-8">
                    <Checkbox
                      label="Select all on this page"
                      checked={allChecked}
                      onChange={(on) =>
                        setSelected((prev) => {
                          const next = new Map(prev);
                          selectable.forEach((f) => (on ? next.set(f.id, f) : next.delete(f.id)));
                          return next;
                        })
                      }
                    />
                  </th>
                  <SortTh label="Name" by="name" sort={sort} onSort={toggleSort} />
                  <th className="th">Type</th>
                  <SortTh label="Size" by="size" sort={sort} onSort={toggleSort} right />
                  <SortTh label="Modified" by="modified" sort={sort} onSort={toggleSort} />
                  <th className="th">Status</th>
                  <SortTh label="Saving" by="savings" sort={sort} onSort={toggleSort} right />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {files.map((f) => {
                  const status = REC_STATUS[f.recommendation_type] || REC_STATUS.keep;
                  return (
                    <tr key={f.id} onClick={() => openFile(f)} className="cursor-pointer hover:bg-canvas">
                      <td className="td w-8">
                        {f.is_google_workspace_file ? (
                          <Tip content="Google Docs/Sheets/Slides have no file content to put in a ZIP.">
                            <span><Checkbox label={`Select ${f.name}`} disabled /></span>
                          </Tip>
                        ) : (
                          <Checkbox label={`Select ${f.name}`} checked={selected.has(f.id)} onChange={() => toggle(f)} />
                        )}
                      </td>
                      <td className="td max-w-[340px]">
                        <div className="truncate font-medium text-ink">{f.name}</div>
                        {f.folder_path && <div className="truncate text-[11px] text-faint">{f.folder_path}</div>}
                      </td>
                      <td className="td mono text-[12px] text-sub">{f.extension || f.category}</td>
                      <td className="td mono text-right">{formatBytes(f.size_bytes)}</td>
                      <td className="td whitespace-nowrap text-sub">{formatDate(f.modified_time)}</td>
                      <td className="td"><Badge tone={status.tone}>{status.label}</Badge></td>
                      <td className="td mono text-right text-ok-ink">{f.estimated_savings_bytes ? formatBytes(f.estimated_savings_bytes) : <span className="text-faint">—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > 0 && (
          <div className="flex items-center justify-between border-t border-line px-4 py-2 text-[12px] text-sub">
            <span>
              <span className="mono">{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)}</span> of <span className="mono">{data.total}</span> files
            </span>
            <div className="flex gap-1">
              <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <Button size="sm" disabled={page * PAGE_SIZE >= data.total} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          </div>
        )}
      </Card>

      <BatchDock
        count={selected.size}
        bytes={selectedBytes}
        actionLabel="Archive to ZIP"
        actionIcon={Archive}
        onAction={() => setConfirming(true)}
        onClear={() => setSelected(new Map())}
      />

      <ConfirmDialog
        open={confirming}
        title={`Archive ${selected.size} file${selected.size === 1 ? "" : "s"} into one ZIP?`}
        description={`${formatBytes(selectedBytes)} in total. The ZIP is uploaded and verified before any original is touched.`}
        consequences={[
          { kind: "undoable", text: "Originals move to Drive's Trash — restore each from History & Restore." },
          { kind: "permanent", text: "Google empties Drive's Trash after 30 days; after that only the ZIP remains." },
          { kind: "info", text: "Links and sharing of the originals don't carry over to the ZIP." },
        ]}
        confirmLabel="Archive"
        busy={busy}
        onConfirm={archive}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}

function SortTh({ label, by, sort, onSort, right }) {
  const active = sort.by === by;
  const Icon = !active ? ArrowUpDown : sort.order === "desc" ? ArrowDown : ArrowUp;
  return (
    <th className={`th ${right ? "text-right" : ""}`}>
      <button onClick={() => onSort(by)} className={`inline-flex items-center gap-1 uppercase ${active ? "text-ink" : ""}`}>
        {label}
        <Icon className="h-3 w-3" />
      </button>
    </th>
  );
}
