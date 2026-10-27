import { useLocation } from "react-router-dom";
import { Menu, RefreshCw } from "lucide-react";
import { Button } from "../ui/button.jsx";
import { StripedBar } from "../ui/progress.jsx";
import { useScan } from "../../context/scan.jsx";
import ProfileMenu from "./ProfileMenu.jsx";
import { routeMeta } from "./nav.js";

export default function TopBar({ onMenu }) {
  const { pathname } = useLocation();
  const { job, scanning, runDrive } = useScan();
  const meta = routeMeta(pathname);
  const message = job?.status === "queued" ? "Queued — waiting for the background worker…" : job?.message || "Starting…";

  return (
    <header className="shrink-0 border-b border-line bg-canvas">
      <div className="flex h-14 items-center gap-3 px-4 lg:px-6">
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={onMenu} aria-label="Open navigation">
          <Menu className="h-4 w-4" />
        </Button>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-ink">{meta.label}</div>
          <div className="text-[11px] uppercase tracking-[0.04em] text-faint">{meta.source}</div>
        </div>
        <Button variant="primary" onClick={runDrive} disabled={scanning} className="ml-auto">
          <RefreshCw className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} strokeWidth={2} />
          <span className="hidden sm:inline">{scanning ? "Scanning…" : "Run Scan"}</span>
        </Button>
        <ProfileMenu />
      </div>
      {scanning && (
        <div className="px-4 pb-2 lg:px-6" role="status" aria-live="polite">
          <div className="mb-1 flex justify-between text-[11px]">
            <span className="mono truncate text-sub">{message}</span>
            {job?.progress != null && <span className="mono text-faint">{Math.round(job.progress)}%</span>}
          </div>
          <StripedBar percent={job?.status === "queued" ? 3 : job?.progress || 3} />
        </div>
      )}
    </header>
  );
}
