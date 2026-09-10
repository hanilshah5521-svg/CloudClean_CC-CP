export function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 MB";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(gb >= 10 ? 1 : 2)} GB`;
  const mb = bytes / 1024 ** 2;
  if (mb >= 1) return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

export function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function monthsAgo(days) {
  const m = Math.floor((days || 0) / 30);
  if (m < 1) return "recently";
  return `${m} month${m === 1 ? "" : "s"} ago`;
}
