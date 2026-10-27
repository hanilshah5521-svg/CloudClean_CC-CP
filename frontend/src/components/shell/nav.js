import { ChartColumn, Copy, Film, FolderInput, History, LayoutDashboard, Settings, Users } from "lucide-react";

/** Sidebar sections, in order. `source` is what the section works on. */
export const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, source: "Google Drive" },
  { to: "/accounts", label: "Accounts", icon: Users, source: "All linked accounts" },
  { to: "/duplicates", label: "Duplicates", icon: Copy, source: "Google Drive" },
  { to: "/organize", label: "Organize", icon: FolderInput, source: "Google Drive" },
  { to: "/compression", label: "Compression", icon: Film, source: "Google Drive" },
  { to: "/history", label: "History & Restore", icon: History, source: "Google Drive" },
  { to: "/analytics", label: "Analytics", icon: ChartColumn, source: "Google Drive" },
  { to: "/settings", label: "Settings", icon: Settings, source: "Account" },
];

export const routeMeta = (pathname) => NAV.find((n) => pathname.startsWith(n.to)) || NAV[0];
