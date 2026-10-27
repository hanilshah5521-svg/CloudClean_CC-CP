import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { HardDrive } from "lucide-react";
import { api } from "../../services/api.js";
import { useScan } from "../../context/scan.jsx";
import { cn } from "../../lib/cn.js";
import { formatBytes } from "../../utils/format.js";
import { NAV } from "./nav.js";

export default function Sidebar({ onNavigate }) {
  const { version } = useScan();
  const [storage, setStorage] = useState(null);

  useEffect(() => {
    api.getStorage().then(setStorage, () => setStorage(null));
  }, [version]);

  const used = storage?.used_percent ?? 0;

  return (
    <div className="flex h-full flex-col bg-panel">
      <div className="border-b border-line px-4 py-4">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-ink text-canvas">
            <HardDrive className="h-4 w-4" strokeWidth={2} />
          </div>
          <span className="text-[15px] font-semibold text-ink">CloudClean</span>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Sections">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "tactile mb-px flex h-8 items-center gap-2.5 rounded px-2.5 text-[13px]",
                isActive ? "bg-surface font-medium text-ink shadow-[inset_2px_0_0_rgb(var(--accent))]" : "text-sub hover:bg-ink/[0.05] hover:text-ink",
              )
            }
          >
            <item.icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-line px-4 py-3">
        <div className="flex items-baseline justify-between text-[11px]">
          <span className="font-medium uppercase tracking-[0.04em] text-faint">Storage</span>
          <span className="mono text-sub">{storage ? `${used.toFixed(1)}%` : "—"}</span>
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-sm bg-track">
          <div
            className={cn("h-full", used >= 90 ? "bg-bad" : used >= 75 ? "bg-warn" : "bg-accent")}
            style={{ width: `${Math.min(100, used)}%` }}
          />
        </div>
        <div className="mono mt-1 text-[11px] text-sub">
          {storage ? `${formatBytes(storage.used_bytes)} / ${formatBytes(storage.quota_bytes)}` : "Not analyzed yet"}
        </div>
      </div>
    </div>
  );
}
