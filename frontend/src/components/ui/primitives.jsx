import { cva } from "class-variance-authority";
import { cn } from "../../lib/cn.js";
import { formatBytes } from "../../utils/format.js";

export function Card({ title, subtitle, action, className, bodyClassName, children }) {
  return (
    <section className={cn("rounded-lg border border-line bg-surface", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[12px] text-sub">{subtitle}</p>}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

const badge = cva("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-[11px] font-medium", {
  variants: {
    tone: {
      neutral: "border-line bg-canvas text-sub",
      accent: "border-accent/25 bg-accent-soft text-accent-ink",
      ok: "border-ok/25 bg-ok-soft text-ok-ink",
      warn: "border-warn/30 bg-warn-soft text-warn-ink",
      bad: "border-bad/25 bg-bad-soft text-bad-ink",
      info: "border-info/25 bg-info-soft text-info-ink",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ tone, mono, className, children }) {
  return <span className={cn(badge({ tone }), mono && "mono", className)}>{children}</span>;
}

export function Mono({ className, children }) {
  return <span className={cn("mono", className)}>{children}</span>;
}

export function Bytes({ value, className }) {
  return <span className={cn("mono", className)}>{formatBytes(value)}</span>;
}

export function Stat({ label, value, sub, tone, className }) {
  const color = { ok: "text-ok-ink", warn: "text-warn-ink", bad: "text-bad-ink", accent: "text-accent-ink" }[tone] || "text-ink";
  return (
    <div className={cn("rounded-lg border border-line bg-surface px-4 py-3", className)}>
      <div className="text-[11px] font-medium uppercase tracking-[0.04em] text-faint">{label}</div>
      <div className={cn("mono mt-1 text-[22px] font-medium leading-tight", color)}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-sub">{sub}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, subtitle, action }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {Icon && <Icon className="mb-3 h-5 w-5 text-faint" strokeWidth={1.75} />}
      <p className="text-[13px] font-medium text-ink">{title}</p>
      {subtitle && <p className="mt-1 max-w-md text-[12px] text-sub">{subtitle}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function SkeletonRows({ rows = 6, cols = 5 }) {
  return (
    <div className="divide-y divide-line" aria-hidden>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex h-9 items-center gap-4 px-3">
          {Array.from({ length: cols }, (_, c) => (
            <div key={c} className="h-2.5 animate-pulse rounded-sm bg-track" style={{ width: c === 0 ? "32%" : `${10 + ((r + c) % 3) * 4}%` }} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Horizontal bar split into labelled segments of a whole (quota, classes…). */
export function SegmentedBar({ segments, total, marker, height = "h-2.5" }) {
  const whole = total || segments.reduce((s, x) => s + x.value, 0) || 1;
  return (
    <div className={cn("relative flex w-full overflow-hidden rounded-sm bg-track", height)}>
      {segments.map((s) =>
        s.value > 0 ? (
          <div key={s.key} className="h-full" style={{ width: `${(s.value / whole) * 100}%`, background: s.color }} title={`${s.label}: ${formatBytes(s.value)}`} />
        ) : null,
      )}
      {marker != null && (
        <div className="absolute inset-y-0 border-r-2 border-dashed border-ok" style={{ left: 0, width: `${Math.min(100, (marker / whole) * 100)}%` }} title="After optimization" />
      )}
    </div>
  );
}

export function Legend({ items }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-sub">
      {items.map((i) => (
        <span key={i.key} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ background: i.color }} />
          {i.label}
          <span className="mono text-ink">{i.text ?? formatBytes(i.value)}</span>
        </span>
      ))}
    </div>
  );
}

export function PageHeader({ title, description, actions }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[18px] font-semibold text-ink">{title}</h1>
        {description && <p className="mt-0.5 max-w-3xl text-[13px] text-sub">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Notice({ tone = "info", icon: Icon, children, className }) {
  const styles = {
    info: "border-info/25 bg-info-soft text-info-ink",
    warn: "border-warn/30 bg-warn-soft text-warn-ink",
    bad: "border-bad/25 bg-bad-soft text-bad-ink",
    ok: "border-ok/25 bg-ok-soft text-ok-ink",
  }[tone];
  return (
    <div className={cn("flex items-start gap-2 rounded border px-3 py-2 text-[12px]", styles, className)}>
      {Icon && <Icon className="mt-px h-3.5 w-3.5 shrink-0" strokeWidth={2} />}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** A compact pill used for filters (single choice). */
export function FilterPills({ options, value, onChange }) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "tactile h-7 rounded border px-2.5 text-[12px] font-medium",
            value === o.value ? "border-accent bg-accent-soft text-accent-ink" : "border-line bg-surface text-sub hover:border-line-strong hover:text-ink",
          )}
        >
          {o.label}
          {o.count != null && <span className="mono ml-1.5 text-faint">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}
