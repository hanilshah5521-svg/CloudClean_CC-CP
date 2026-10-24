export function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 MB";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(gb >= 10 ? 1 : 2)} GB`;
  const mb = bytes / 1024 ** 2;
  if (mb >= 1) return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

// The API returns naive UTC timestamps.
export const fromUtc = (value) => new Date(/Z|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);

export function formatDate(value) {
  if (!value) return "—";
  return fromUtc(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(value) {
  if (!value) return "—";
  return fromUtc(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function daysUntil(value) {
  if (!value) return null;
  return Math.max(0, Math.ceil((fromUtc(value) - Date.now()) / 86_400_000));
}

export function monthsAgo(days) {
  const m = Math.floor((days || 0) / 30);
  if (m < 1) return "recently";
  return `${m} month${m === 1 ? "" : "s"} ago`;
}

export function formatDuration(seconds) {
  if (!seconds) return "—";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
}

export function formatMbps(kbps) {
  return kbps ? `${(kbps / 1000).toFixed(1)} Mbps` : "—";
}

export function pct(part, whole) {
  return whole ? Math.min(100, (part / whole) * 100) : 0;
}

export const shortHash = (hash) => (hash ? hash.slice(0, 8) : "—");
