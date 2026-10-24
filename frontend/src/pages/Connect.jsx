import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { FlaskConical, HardDrive, KeyRound, TriangleAlert } from "lucide-react";
import { api } from "../services/api.js";
import { useUser } from "../hooks/useUser.jsx";
import { Button } from "../components/ui/button.jsx";
import { Notice } from "../components/ui/primitives.jsx";
import ThemeToggle from "../components/ThemeToggle.jsx";

export const CONNECT_ERRORS = {
  oauth_failed: "Google sign-in failed. Please try again.",
  missing_code: "Google didn't return an authorization code. Please try again.",
  access_denied: "You declined the requested permissions — CloudClean needs Drive access to analyze your storage.",
  state_mismatch: "That sign-in link was stale or didn't start here. Please try connecting again.",
  not_configured: "Google sign-in isn't set up on this server yet — add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env and restart the backend.",
};

/** Standalone screen for signed-out visitors. */
export default function Connect() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(params.get("error") ? CONNECT_ERRORS[params.get("error")] || "Something went wrong." : null);
  const navigate = useNavigate();
  const { refresh } = useUser();

  useEffect(() => {
    api.getAuthStatus().then(setStatus, () => setStatus({ google_configured: false, gmail_enabled: false }));
  }, []);

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

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-[880px]">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-ink text-canvas">
            <HardDrive className="h-4 w-4" strokeWidth={2} />
          </div>
          <span className="text-[17px] font-semibold text-ink">CloudClean</span>
          <span className="ml-2 hidden text-[13px] text-sub sm:inline">Storage optimization for Google Drive, Gmail and AWS S3</span>
          <ThemeToggle className="ml-auto" />
        </div>

        {error && (
          <Notice tone="bad" icon={TriangleAlert} className="mb-4">
            {error}
          </Notice>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <section className="rounded-lg border border-line bg-surface p-5">
            <div className="flex items-center gap-2 text-[13px] font-semibold text-ink">
              <KeyRound className="h-4 w-4 text-accent-ink" /> Connect your Google account
            </div>
            <ul className="mt-3 space-y-1.5 text-[12px] text-sub">
              <li><span className="mono text-ink">drive</span> — read file metadata; replace, move or trash files only when you confirm</li>
              {status?.gmail_enabled && <li><span className="mono text-ink">gmail.modify</span> — optional: list large emails, move them to Gmail Trash</li>}
              <li>Nothing is ever permanently deleted without a separate confirmation.</li>
            </ul>
            {status && !status.google_configured && (
              <Notice tone="warn" icon={TriangleAlert} className="mt-4">
                {CONNECT_ERRORS.not_configured}
              </Notice>
            )}
            <Button
              variant="primary"
              size="lg"
              className="mt-4 w-full"
              disabled={busy || !status?.google_configured}
              onClick={() => {
                setBusy(true);
                window.location.href = api.googleLoginUrl;
              }}
            >
              Connect Google Drive
            </Button>
          </section>

          <section className="rounded-lg border border-line bg-surface p-5">
            <div className="flex items-center gap-2 text-[13px] font-semibold text-ink">
              <FlaskConical className="h-4 w-4 text-warn" /> Demo Mode
            </div>
            <p className="mt-3 text-[12px] text-sub">
              A simulated account: <span className="mono text-ink">105</span> Drive files, <span className="mono text-ink">36</span> large
              emails and four S3 buckets — with duplicates, oversized videos and untiered data to clean up. Nothing real is touched.
            </p>
            <Button size="lg" className="mt-4 w-full" disabled={busy} onClick={startDemo}>
              Try Demo Mode
            </Button>
          </section>
        </div>
      </div>
    </div>
  );
}
