import { Link } from "react-router-dom";

const FEATURES = [
  { icon: "🧠", title: "Intelligent Analysis", body: "Rule-based, fully explainable analysis of your entire Drive — no black-box AI, no paid API." },
  { icon: "🧬", title: "Duplicate Detection", body: "Three-level matching (name, size, content hash) groups duplicates and recommends which copy to keep." },
  { icon: "🗜️", title: "Smart Compression", body: "Real JPEG/PNG/WebP and PDF compression, computed before your eyes — original vs. optimized, byte for byte." },
  { icon: "🗄️", title: "Lifecycle Management", body: "Inactive files get archived into ZIPs, not silently judged as 'unnecessary'." },
  { icon: "📊", title: "Storage Insights", body: "A transparent Optimization Score and a savings calculator with honest, non-linear pricing estimates." },
  { icon: "🛡️", title: "Safe Optimization", body: "Nothing is ever deleted automatically. Every destructive step needs your explicit confirmation." },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-brand-50 to-white">
      <header className="max-w-6xl mx-auto px-6 py-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-brand-600 flex items-center justify-center text-white font-bold">C</div>
          <span className="text-lg font-semibold text-slate-900">CloudClean</span>
        </div>
        <Link to="/connect" className="text-sm font-medium text-brand-700 hover:underline">Connect Google Drive</Link>
      </header>

      <section className="max-w-4xl mx-auto px-6 pt-16 pb-20 text-center">
        <h1 className="text-4xl sm:text-5xl font-bold text-slate-900 tracking-tight">
          Clean Your Google Drive. <span className="text-brand-600">Recover Your Storage.</span>
        </h1>
        <p className="mt-5 text-lg text-slate-600 max-w-2xl mx-auto">
          CloudClean intelligently analyzes your Drive, finds redundant files, identifies compression
          opportunities, and helps you recover valuable storage — safely, and with full explanations.
        </p>
        <div className="mt-8 flex items-center justify-center gap-4">
          <Link to="/connect" className="px-6 py-3 rounded-xl bg-brand-600 text-white font-semibold shadow-sm hover:bg-brand-700">
            Connect Google Drive
          </Link>
          <Link to="/connect?demo=1" className="px-6 py-3 rounded-xl bg-white text-slate-700 font-semibold border border-slate-200 hover:bg-slate-50">
            Try Demo Mode
          </Link>
        </div>
      </section>

      <section className="max-w-6xl mx-auto px-6 pb-24 grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {FEATURES.map((f) => (
          <div key={f.title} className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
            <div className="text-2xl mb-3">{f.icon}</div>
            <h3 className="font-semibold text-slate-900 mb-1">{f.title}</h3>
            <p className="text-sm text-slate-500">{f.body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
