import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Folder, FolderInput, FolderOpen, FolderPlus } from "lucide-react";
import { api } from "../services/api.js";
import { useScan } from "../context/scan.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { useGoogleLinks } from "../hooks/useGoogleLinks.js";
import { IconLink } from "../components/GoogleLinks.jsx";
import { DEMO_LINK_REASON } from "../components/details.js";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, PageHeader, SkeletonRows } from "../components/ui/primitives.jsx";
import { Field } from "../components/ui/controls.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import { formatBytes } from "../utils/format.js";

export default function Organize() {
  const [suggestions, setSuggestions] = useState(null);
  const [names, setNames] = useState({});
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const { version } = useScan();
  const toast = useToast();
  const links = useGoogleLinks();

  const load = useCallback(async () => {
    const data = await api.getOrganizeSuggestions();
    setSuggestions(data);
    setNames((prev) => {
      const next = { ...prev };
      for (const s of data) if (!(s.id in next)) next[s.id] = s.folder_name;
      return next;
    });
  }, []);

  useEffect(() => {
    load().catch((e) => toast(e.message, "error"));
  }, [load, version, toast]);

  async function apply() {
    setBusy(true);
    try {
      const res = await api.applyOrganize(confirm.id, names[confirm.id]);
      toast(res.message, res.failed?.length ? "error" : "success");
      setConfirm(null);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function dismiss(id) {
    try {
      await api.dismissOrganize(id);
      await load();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  if (!suggestions) return <Card bodyClassName="p-0"><SkeletonRows rows={6} /></Card>;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Organize"
        description="Loose files sharing one naming pattern (a prefix followed by a counter, date or timestamp) gathered into one folder. Files are moved, not copied — links and sharing stay the same."
      />

      {suggestions.length === 0 ? (
        <Card>
          <EmptyState icon={FolderInput} title="Nothing to organize" subtitle="No folder has 3 or more loose files sharing a naming pattern. Run a scan after adding files." />
        </Card>
      ) : (
        suggestions.map((s) => {
          const name = (names[s.id] ?? s.folder_name).trim();
          const reuses = s.uses_existing_folder && name.toLowerCase() === s.folder_name.toLowerCase();
          return (
            <Card
              key={s.id}
              title={<span>Files named like <span className="mono">{s.pattern}</span></span>}
              subtitle={<span><span className="mono">{s.count}</span> files · <span className="mono">{formatBytes(s.total_bytes)}</span> · in {s.parent_name}</span>}
              action={
                <span className="flex items-center gap-1">
                  {reuses ? <Badge tone="ok">Uses existing folder</Badge> : <Badge tone="accent">New folder</Badge>}
                  <IconLink href={links.folder(s.parent_id)} label={`Open ${s.parent_name} in Drive`} icon={FolderOpen} disabledReason={DEMO_LINK_REASON} />
                </span>
              }
            >
              <div className="grid items-start gap-4 lg:grid-cols-[1fr_auto_1fr]">
                <TreePreview label="Before" root={s.parent_name} items={s.names} more={s.count - s.names.length} />
                <ArrowRight className="mx-auto hidden h-4 w-4 text-faint lg:mt-10 lg:block" />
                <TreePreview label="After" root={s.parent_name} folder={name || "…"} items={s.names} more={s.count - s.names.length} />
              </div>
              <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-4">
                <Field label="Destination folder" className="w-full sm:w-72">
                  <input value={names[s.id] ?? s.folder_name} maxLength={120} onChange={(e) => setNames((p) => ({ ...p, [s.id]: e.target.value }))} className="field" />
                </Field>
                <Button variant="primary" disabled={!name} onClick={() => setConfirm(s)}>
                  <FolderPlus className="h-3.5 w-3.5" /> Organize {s.count} files
                </Button>
                <Button variant="ghost" onClick={() => dismiss(s.id)}>Dismiss</Button>
              </div>
            </Card>
          );
        })
      )}

      <ConfirmDialog
        open={!!confirm}
        title={confirm ? `Move ${confirm.count} files into “${(names[confirm.id] || "").trim()}”?` : ""}
        description={confirm ? `Inside ${confirm.parent_name}.` : ""}
        consequences={[
          { kind: "undoable", text: "Undo from History & Restore moves every file back to where it was." },
          { kind: "info", text: "Files keep their IDs, share links and permissions — only their folder changes." },
        ]}
        confirmLabel="Organize"
        busy={busy}
        onConfirm={apply}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

function TreePreview({ label, root, folder, items, more }) {
  return (
    <div className="rounded border border-line bg-canvas p-3">
      <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.04em] text-faint">{label}</div>
      <div className="mono space-y-0.5 text-[12px] text-ink">
        <div className="flex items-center gap-1.5"><Folder className="h-3.5 w-3.5 text-sub" /> {root}</div>
        {folder && (
          <div className="flex items-center gap-1.5 pl-4 font-medium text-accent-ink">
            <Folder className="h-3.5 w-3.5" /> {folder}
          </div>
        )}
        {items.slice(0, 5).map((n) => (
          <div key={n} className={`truncate text-sub ${folder ? "pl-9" : "pl-4"}`}>{n}</div>
        ))}
        {Math.max(0, items.length - 5) + Math.max(0, more) > 0 && (
          <div className={`text-faint ${folder ? "pl-9" : "pl-4"}`}>+ {Math.max(0, items.length - 5) + Math.max(0, more)} more</div>
        )}
      </div>
    </div>
  );
}
