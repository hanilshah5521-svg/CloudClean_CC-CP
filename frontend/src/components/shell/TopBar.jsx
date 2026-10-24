import { useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Menu, RefreshCw, Search } from "lucide-react";
import { Button } from "../ui/button.jsx";
import { StripedBar } from "../ui/progress.jsx";
import { useScan } from "../../context/scan.jsx";
import { routeMeta } from "./nav.js";

export default function TopBar({ onMenu }) {
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { job, scanning, runDrive, s3Scanning, runS3 } = useScan();
  const meta = routeMeta(pathname);
  const onS3 = pathname.startsWith("/s3");
  const busy = onS3 ? s3Scanning : scanning;
  const [query, setQuery] = useState(params.get("search") || "");

  useEffect(() => setQuery(pathname.startsWith("/files") ? params.get("search") || "" : ""), [pathname, params]);

  function search(e) {
    e.preventDefault();
    const q = query.trim();
    navigate(q ? `/files?search=${encodeURIComponent(q)}` : "/files");
  }

  const message = onS3 ? "Listing buckets, versions and uploads…" : job?.status === "queued" ? "Queued — waiting for the background worker…" : job?.message || "Starting…";

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
        <form onSubmit={search} className="relative ml-auto hidden w-72 xl:block" role="search">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search Drive files by name"
            aria-label="Search Drive files by name"
            className="field pl-8"
          />
        </form>
        <Button variant="primary" onClick={onS3 ? runS3 : runDrive} disabled={busy} className="ml-auto xl:ml-0">
          <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} strokeWidth={2} />
          {busy ? "Scanning…" : onS3 ? "Scan buckets" : "Run Scan"}
        </Button>
      </div>
      {busy && (
        <div className="px-4 pb-2 lg:px-6" role="status" aria-live="polite">
          <div className="mb-1 flex justify-between text-[11px]">
            <span className="mono truncate text-sub">{message}</span>
            {!onS3 && job?.progress != null && <span className="mono text-faint">{Math.round(job.progress)}%</span>}
          </div>
          <StripedBar percent={onS3 ? 60 : job?.status === "queued" ? 3 : job?.progress || 3} />
        </div>
      )}
    </header>
  );
}
