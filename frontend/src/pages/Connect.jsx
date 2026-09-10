import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../services/api.js";
import { useUser } from "../hooks/useUser.jsx";

const ERROR_MESSAGES = {
  oauth_failed: "Google sign-in failed. Please try again.",
  missing_code: "Google didn't return an authorization code. Please try again.",
  access_denied: "You declined the requested permissions — CloudClean needs Drive access to analyze your storage.",
};

export default function Connect() {
  const [params] = useSearchParams();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(params.get("error") ? ERROR_MESSAGES[params.get("error")] || "Something went wrong." : null);
  const navigate = useNavigate();
  const { refresh } = useUser();

  async function startDemo() {
    setBusy(true);
    try {
      await api.demoLogin();
      await refresh();
      navigate("/dashboard");
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function startGoogle() {
    setBusy(true);
    try {
      const { url } = await api.googleAuthUrl();
      window.location.href = url;
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  useEffect(() => {
    if (params.get("demo") === "1") startDemo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="max-w-md w-full bg-white rounded-2xl border border-slate-200 shadow-sm p-8">
        <div className="h-10 w-10 rounded-lg bg-brand-600 flex items-center justify-center text-white font-bold mb-4">C</div>
        <h1 className="text-xl font-semibold text-slate-900 mb-2">Connect your Google Drive</h1>
        <p className="text-sm text-slate-500 mb-5">
          CloudClean requests Drive access so it can read your file metadata, and — only when you
          explicitly approve an action — upload optimized replacements and move originals to Trash.
          It never deletes anything permanently or reads file content without your request.
        </p>

        {error && <div className="mb-4 text-sm text-red-600 bg-red-50 rounded-lg p-3">{error}</div>}

        <button
          onClick={startGoogle}
          disabled={busy}
          className="w-full px-4 py-3 rounded-xl bg-brand-600 text-white font-semibold hover:bg-brand-700 disabled:opacity-60 mb-3"
        >
          {busy ? "Connecting…" : "Connect Google Drive"}
        </button>
        <button
          onClick={startDemo}
          disabled={busy}
          className="w-full px-4 py-3 rounded-xl bg-white text-slate-700 font-semibold border border-slate-200 hover:bg-slate-50 disabled:opacity-60"
        >
          Try Demo Mode instead
        </button>
        <p className="text-xs text-slate-400 mt-4 text-center">
          Demo Mode uses simulated Drive data — no Google account required, nothing real is touched.
        </p>
      </div>
    </div>
  );
}
