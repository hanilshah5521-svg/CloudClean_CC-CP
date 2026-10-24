import { ExternalLink, FolderOpen } from "lucide-react";
import { formatBytes, formatDate, monthsAgo } from "../utils/format.js";

/** How each recommendation_type is labelled across the app. */
export const REC_STATUS = {
  compress: { label: "Compressible", tone: "accent" },
  duplicate: { label: "Duplicate", tone: "warn" },
  version: { label: "Version", tone: "warn" },
  archive: { label: "Archive candidate", tone: "info" },
  review: { label: "Large — review", tone: "info" },
  already_optimized: { label: "Optimized", tone: "ok" },
  keep: { label: "No action", tone: "neutral" },
};

export const isDemoId = (id) => typeof id === "string" && id.startsWith("demo-");
export const DEMO_LINK_REASON = "Demo Mode: this isn't in a real Google account.";

/** Drawer link actions for a Drive file; `links` comes from useGoogleLinks(). */
export function driveLinkActions(f, links) {
  return [
    { label: "Open in Drive", icon: ExternalLink, href: links.file(f), disabledReason: DEMO_LINK_REASON },
    {
      label: "Show in folder",
      icon: FolderOpen,
      href: links.folder(f.parent_id),
      disabledReason: links.demo ? DEMO_LINK_REASON : "Not in one of your folders (shared with you).",
    },
  ];
}

/** Details-drawer description of a Drive file (see context/drawer.jsx). */
export function fileDetails(f, actions = [], links = null) {
  const status = REC_STATUS[f.recommendation_type] || REC_STATUS.keep;
  return {
    kind: "Google Drive file",
    title: f.name,
    subtitle: f.folder_path || undefined,
    badges: [status, { label: f.category, tone: "neutral" }],
    fields: [
      { label: "MIME type", value: f.mime_type, mono: true },
      { label: "Size", value: formatBytes(f.size_bytes), mono: true },
      {
        label: "Checksum",
        value: f.content_hash || (f.is_google_workspace_file ? "None (Google Docs have no checksum)" : "—"),
        mono: true,
      },
      { label: "Folder", value: f.folder_path || "—" },
      { label: "Created", value: formatDate(f.created_time) },
      { label: "Modified", value: f.modified_time ? `${formatDate(f.modified_time)} · ${monthsAgo(f.inactivity_days)}` : "—" },
      { label: "Potential saving", value: f.estimated_savings_bytes ? formatBytes(f.estimated_savings_bytes) : "—", mono: true },
      { label: "Drive ID", value: f.drive_id, mono: true },
    ],
    actions: links ? [...actions, ...driveLinkActions(f, links)] : actions,
  };
}
