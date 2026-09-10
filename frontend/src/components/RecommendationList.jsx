import { Link } from "react-router-dom";
import { formatBytes } from "../utils/format.js";

const TYPE_META = {
  compress: { label: "Compress", icon: "🗜️", to: "/compression" },
  duplicate: { label: "Review duplicates", icon: "🧬", to: "/duplicates" },
  archive: { label: "Archive", icon: "🗄️", to: "/files?filter=archive_candidate" },
  review: { label: "Review", icon: "🔍", to: "/files" },
};

const RISK_STYLE = {
  low: "bg-emerald-50 text-emerald-700",
  medium: "bg-amber-50 text-amber-700",
  high: "bg-red-50 text-red-700",
};

export default function RecommendationList({ recommendations, limit }) {
  const items = limit ? recommendations.slice(0, limit) : recommendations;
  if (!items.length) {
    return <p className="text-sm text-slate-400 py-6 text-center">No recommendations yet — run an analysis to get started.</p>;
  }
  return (
    <ol className="space-y-3">
      {items.map((rec, i) => {
        const meta = TYPE_META[rec.type] || TYPE_META.review;
        return (
          <li key={rec.id} className="flex items-start gap-3 p-4 rounded-xl border border-slate-100 hover:border-slate-200">
            <span className="text-sm font-semibold text-slate-400 mt-0.5 w-5">{i + 1}.</span>
            <span className="text-xl">{meta.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-slate-900">{meta.label}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${RISK_STYLE[rec.risk] || RISK_STYLE.low}`}>
                  {rec.risk} risk
                </span>
                <span className="text-xs text-slate-400">{Math.round(rec.confidence * 100)}% confidence</span>
              </div>
              <p className="text-xs text-slate-500 mt-1 whitespace-pre-line line-clamp-3">{rec.reason}</p>
            </div>
            <div className="text-right shrink-0">
              <div className="text-sm font-semibold text-slate-900">{formatBytes(rec.estimated_saving_bytes)}</div>
              <Link to={meta.to} className="text-xs font-medium text-brand-600 hover:underline">
                Review →
              </Link>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
