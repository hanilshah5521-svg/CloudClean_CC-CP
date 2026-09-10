import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useUser } from "../hooks/useUser.jsx";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "📊" },
  { to: "/files", label: "File Explorer", icon: "🗂️" },
  { to: "/duplicates", label: "Duplicates", icon: "🧬" },
  { to: "/compression", label: "Compression", icon: "🗜️" },
  { to: "/analytics", label: "Analytics", icon: "📈" },
  { to: "/history", label: "History", icon: "🕘" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
];

export default function AppShell() {
  const { user, logout } = useUser();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex bg-slate-50">
      <aside className="w-60 shrink-0 bg-white border-r border-slate-200 flex flex-col">
        <div className="px-5 py-5 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-brand-600 flex items-center justify-center text-white font-bold">C</div>
            <span className="text-lg font-semibold text-slate-900">CloudClean</span>
          </div>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
                }`
              }
            >
              <span>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="px-3 py-4 border-t border-slate-100">
          <div className="flex items-center gap-2 px-2 mb-2">
            <div className="h-8 w-8 rounded-full bg-slate-200 flex items-center justify-center text-xs font-semibold text-slate-600">
              {(user?.name || "?").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium text-slate-800 truncate">{user?.name || "—"}</div>
              <div className="text-xs text-slate-400 truncate">{user?.email}</div>
            </div>
          </div>
          <button
            onClick={async () => {
              await logout();
              navigate("/");
            }}
            className="w-full text-left px-2 py-1.5 text-sm text-slate-500 hover:text-red-600 rounded-md hover:bg-red-50"
          >
            Sign out
          </button>
        </div>
      </aside>
      <div className="flex-1 flex flex-col min-w-0">
        {user?.is_demo && (
          <div className="bg-amber-400 text-amber-950 text-center text-sm font-semibold py-1.5">
            DEMO MODE — viewing simulated Drive data, not your real Google Drive
          </div>
        )}
        <main className="flex-1 p-8 max-w-6xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
