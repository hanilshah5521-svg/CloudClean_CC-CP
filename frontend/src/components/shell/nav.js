import {
  ChartColumn, Copy, Database, Film, FolderInput, FolderTree, History, LayoutDashboard, Mail, PlugZap, Settings,
} from "lucide-react";

/** The 11 sections, in sidebar order. `source` is what the section works on. */
export const NAV = [
  { to: "/account", label: "Connect / Demo", icon: PlugZap, source: "Account" },
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, source: "Google Drive" },
  { to: "/files", label: "File Explorer", icon: FolderTree, source: "Google Drive" },
  { to: "/duplicates", label: "Duplicates", icon: Copy, source: "Google Drive" },
  { to: "/organize", label: "Organize", icon: FolderInput, source: "Google Drive" },
  { to: "/compression", label: "Compression", icon: Film, source: "Google Drive" },
  { to: "/gmail", label: "Gmail & Photos", icon: Mail, source: "Gmail" },
  { to: "/history", label: "History & Restore", icon: History, source: "Google Drive" },
  { to: "/analytics", label: "Analytics", icon: ChartColumn, source: "Google Drive" },
  { to: "/s3", label: "AWS S3 Manager", icon: Database, source: "AWS S3" },
  { to: "/settings", label: "Settings", icon: Settings, source: "Account" },
];

export const routeMeta = (pathname) => NAV.find((n) => pathname.startsWith(n.to)) || NAV[1];
