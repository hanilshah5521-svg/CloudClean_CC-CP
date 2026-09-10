import Card from "./Card.jsx";

const FACTOR_LABELS = {
  duplicate_inefficiency: "Duplicate inefficiency",
  compression_opportunity: "Compression opportunity",
  inactive_data: "Inactive data",
  large_file_concentration: "Large file concentration",
};

function ringColor(score) {
  if (score >= 85) return "#10b981";
  if (score >= 60) return "#3b82f6";
  return "#f59e0b";
}

export default function OptimizationScoreCard({ score, summary, breakdown }) {
  const s = score ?? 0;
  const circumference = 2 * Math.PI * 54;
  const offset = circumference * (1 - s / 100);

  return (
    <Card title="Optimization Score" subtitle="Transparent, rule-based — never a black box">
      <div className="flex items-center gap-6">
        <svg width="130" height="130" viewBox="0 0 130 130" className="shrink-0">
          <circle cx="65" cy="65" r="54" fill="none" stroke="#e2e8f0" strokeWidth="12" />
          <circle
            cx="65" cy="65" r="54" fill="none" stroke={ringColor(s)} strokeWidth="12"
            strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
            transform="rotate(-90 65 65)"
          />
          <text x="65" y="60" textAnchor="middle" fontSize="28" fontWeight="700" fill="#0f172a">{s}</text>
          <text x="65" y="80" textAnchor="middle" fontSize="12" fill="#94a3b8">/ 100</text>
        </svg>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-600 mb-3">{summary}</p>
          <div className="space-y-1.5">
            {Object.entries(breakdown || {}).map(([key, pts]) => (
              <div key={key} className="flex items-center justify-between text-xs">
                <span className="text-slate-500">{FACTOR_LABELS[key] || key}</span>
                <span className="font-medium text-slate-700">-{pts} pts</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}
