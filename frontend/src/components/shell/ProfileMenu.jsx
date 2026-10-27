import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Check, ChevronDown, FlaskConical, KeyRound, LogOut, Plus, Settings, Users } from "lucide-react";
import { useAccountActions } from "../../hooks/useAccountActions.js";
import { accountTone, useAccounts } from "../../context/accounts.jsx";
import { cn } from "../../lib/cn.js";
import { formatBytes } from "../../utils/format.js";
import ThemeToggle from "../ThemeToggle.jsx";

const TONE_CLASS = {
  accent: "bg-accent-soft text-accent-ink",
  ok: "bg-ok-soft text-ok-ink",
  warn: "bg-warn-soft text-warn-ink",
  info: "bg-info-soft text-info-ink",
};

/** Top-right account switcher: linked accounts, add another, Demo Mode, theme, sign out. */
export default function ProfileMenu() {
  const { user, status, busy, connectGoogle, startDemo, signOut } = useAccountActions();
  const { summary, accounts, switchTo, addAccount, adding } = useAccounts();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;
  const demo = user.is_demo;
  const canConnect = status?.google_configured;
  const tone = (id) => TONE_CLASS[accountTone(accounts, id)];
  const activeId = summary?.active_id ?? user.id;
  const addLabel = summary?.add_kind === "simulated" ? "Add a simulated account" : "Add Google account";
  const addHint = summary?.add_kind === "simulated"
    ? (summary.can_add ? "A second Drive of the same person, with shared copies" : "Demo Mode has 3 accounts at most")
    : (summary?.can_add ? "Sign in to another of your Google accounts" : "Google sign-in isn't set up on this server");

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account: ${user.email}`}
        className="tactile flex h-9 items-center gap-2 rounded border border-line bg-surface pl-1 pr-2 hover:border-line-strong"
      >
        <Avatar email={user.email} className={tone(activeId)} />
        <span className="hidden max-w-[180px] truncate text-[12px] text-sub md:inline">{user.email}</span>
        {accounts.length > 1 && <span className="mono rounded-sm bg-canvas px-1 text-[10px] text-sub">+{accounts.length - 1}</span>}
        {demo && <span className="hidden rounded-sm bg-warn-soft px-1 text-[10px] font-semibold text-warn-ink md:inline">DEMO</span>}
        <ChevronDown className={cn("h-3.5 w-3.5 text-faint transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div role="menu" className="absolute right-0 top-11 z-50 max-h-[calc(100vh-72px)] w-80 overflow-y-auto rounded-lg border border-line bg-surface shadow-[0_8px_30px_rgb(var(--shade)/0.12)]">
          <div className="border-b border-line px-4 pb-1 pt-3">
            <div className="text-[11px] font-medium uppercase tracking-[0.04em] text-faint">
              {accounts.length > 1 ? `${accounts.length} linked accounts` : "Account"}
            </div>
            <ul className="mt-1.5">
              {(accounts.length ? accounts : [{ id: user.id, email: user.email, active: true }]).map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={a.active}
                    onClick={() => !a.active && switchTo(a.id)}
                    className={cn("-mx-2 flex w-[calc(100%+16px)] items-center gap-2.5 rounded px-2 py-1.5 text-left", !a.active && "hover:bg-ink/[0.05]")}
                  >
                    <Avatar email={a.email} className={tone(a.id)} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] text-ink">{a.email}</span>
                      <span className="block text-[11px] text-faint">
                        {a.quota_bytes ? `${formatBytes(a.used_bytes)} of ${formatBytes(a.quota_bytes)}` : "Not scanned yet"}
                        {a.active ? " · working in this one" : ""}
                      </span>
                    </span>
                    {a.active && <Check className="h-4 w-4 shrink-0 text-accent-ink" />}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="py-1">
            <Item icon={Plus} onClick={addAccount} disabled={!summary?.can_add || adding} hint={addHint}>
              {adding ? "Adding…" : addLabel}
            </Item>
            {accounts.length > 1 && (
              <Link role="menuitem" to="/accounts" className="flex items-center gap-2.5 px-4 py-2 text-[13px] text-ink hover:bg-ink/[0.05]">
                <Users className="h-4 w-4 text-sub" /> All accounts &amp; shared duplicates
              </Link>
            )}
          </div>

          <div className="border-t border-line py-1">
            {demo ? (
              <Item icon={KeyRound} onClick={connectGoogle} disabled={!canConnect}
                    hint={status && !canConnect ? "Google sign-in isn't set up on this server" : "Leaves Demo Mode"}>
                Connect Google account
              </Item>
            ) : (
              <Item icon={KeyRound} onClick={connectGoogle} disabled={!canConnect} hint="Sign in again to refresh access">
                Reconnect Google account
              </Item>
            )}
            <Item icon={FlaskConical} onClick={startDemo} disabled={busy} hint={demo ? "Resets the simulated data" : "Simulated data — your accounts stay connected"}>
              {demo ? "Start a new demo" : "Try Demo Mode"}
            </Item>
            <Link role="menuitem" to="/settings#account" className="flex items-center gap-2.5 px-4 py-2 text-[13px] text-ink hover:bg-ink/[0.05]">
              <Settings className="h-4 w-4 text-sub" /> Account & settings
            </Link>
          </div>

          <div className="flex items-center justify-between border-t border-line px-4 py-2.5">
            <span className="text-[12px] text-sub">Theme</span>
            <ThemeToggle />
          </div>

          <div className="border-t border-line py-1">
            <Item icon={LogOut} onClick={signOut} danger>Sign out</Item>
          </div>
        </div>
      )}
    </div>
  );
}

export function Avatar({ email, className, large }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-semibold",
        large ? "h-9 w-9 text-[14px]" : "h-7 w-7 text-[12px]",
        className || "bg-accent-soft text-accent-ink",
      )}
    >
      {(email || "?").charAt(0).toUpperCase()}
    </span>
  );
}

function Item({ icon: Icon, children, onClick, disabled, hint, danger }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex w-full items-start gap-2.5 px-4 py-2 text-left text-[13px] hover:bg-ink/[0.05] disabled:cursor-not-allowed disabled:opacity-50",
        danger ? "text-bad-ink" : "text-ink",
      )}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", danger ? "text-bad-ink" : "text-sub")} />
      <span className="min-w-0">
        <span className="block">{children}</span>
        {hint && <span className="block text-[11px] text-faint">{hint}</span>}
      </span>
    </button>
  );
}
