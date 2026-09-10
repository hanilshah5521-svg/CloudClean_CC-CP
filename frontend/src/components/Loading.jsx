export function Loading({ label = "Loading…" }) {
  return (
    <div className="flex items-center justify-center py-16 text-slate-400 text-sm gap-2">
      <span className="h-4 w-4 rounded-full border-2 border-slate-300 border-t-brand-600 animate-spin" />
      {label}
    </div>
  );
}

export function EmptyState({ title, subtitle, action }) {
  return (
    <div className="text-center py-16">
      <p className="text-slate-700 font-medium">{title}</p>
      {subtitle && <p className="text-sm text-slate-400 mt-1">{subtitle}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message }) {
  return (
    <div className="text-center py-16">
      <p className="text-red-600 font-medium">Something went wrong</p>
      <p className="text-sm text-slate-400 mt-1">{message}</p>
    </div>
  );
}
