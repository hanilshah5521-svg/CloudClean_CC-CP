import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CircleCheck, FlaskConical, KeyRound, LogOut, Mail, TriangleAlert } from "lucide-react";
import { api } from "../services/api.js";
import { useUser } from "../hooks/useUser.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, Notice, PageHeader } from "../components/ui/primitives.jsx";
import { CONNECT_ERRORS } from "./Connect.jsx";

/** "Connect / Demo": what this session is connected to, and how to switch. */
export default function Account() {
  const { user, refresh, logout } = useUser();
  const [params] = useSearchParams();
  const [status, setStatus] = useState(null);
  const [gmail, setGmail] = useState(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();
  const error = params.get("error") ? CONNECT_ERRORS[params.get("error")] || "Something went wrong." : null;

  useEffect(() => {
    api.getAuthStatus().then(setStatus, () => setStatus(null));
    api.getGmail({ page_size: 1 }).then((g) => setGmail(g.access), () => setGmail(null));
  }, []);

  async function newDemo() {
    setBusy(true);
    try {
      await api.demoLogin();
      await refresh();
      toast("Started a fresh Demo Mode session.");
      navigate("/dashboard");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  const gmailLabel = { demo: ["Simulated", "warn"], granted: ["Granted", "ok"], not_granted: ["Not granted", "bad"] }[gmail] || ["Unknown", "neutral"];

  return (
    <div className="space-y-5">
      <PageHeader title="Connect / Demo" description="What this session is connected to. Switching accounts keeps nothing from the previous one visible." />

      {error && <Notice tone="bad" icon={TriangleAlert}>{error}</Notice>}

      <Card title="Current connection">
        <dl className="divide-y divide-line rounded border border-line text-[13px]">
          <Row label="Account"><span className="mono">{user?.email}</span></Row>
          <Row label="Mode">
            {user?.is_demo ? <Badge tone="warn"><FlaskConical className="h-3 w-3" /> Demo Mode</Badge> : <Badge tone="ok"><CircleCheck className="h-3 w-3" /> Google account</Badge>}
          </Row>
          <Row label="Google Drive">{user?.is_demo ? <Badge tone="warn">Simulated</Badge> : <Badge tone="ok">Connected</Badge>}</Row>
          <Row label="Gmail"><Badge tone={gmailLabel[1]}><Mail className="h-3 w-3" /> {gmailLabel[0]}</Badge></Row>
          <Row label="Google sign-in on this server">
            {status ? (status.google_configured ? <Badge tone="ok">Configured</Badge> : <Badge tone="bad">Not configured</Badge>) : "—"}
          </Row>
        </dl>
      </Card>

      {status && !status.google_configured && <Notice tone="warn" icon={TriangleAlert}>{CONNECT_ERRORS.not_configured}</Notice>}

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Google account" subtitle={user?.is_demo ? "Connect your real Drive (and optionally Gmail)." : "Reconnect to change permissions, e.g. to grant Gmail."}>
          <Button variant="primary" disabled={!status?.google_configured} onClick={() => (window.location.href = api.googleLoginUrl)}>
            <KeyRound className="h-3.5 w-3.5" /> {user?.is_demo ? "Connect Google Drive" : "Reconnect Google account"}
          </Button>
        </Card>
        <Card title="Demo Mode" subtitle="A fresh simulated account: Drive files, large emails and four S3 buckets.">
          <div className="flex flex-wrap gap-2">
            <Button onClick={newDemo} disabled={busy}>
              <FlaskConical className="h-3.5 w-3.5" /> Start a new demo session
            </Button>
            <Button
              variant="ghost"
              onClick={async () => {
                await logout();
                navigate("/connect");
              }}
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[200px_1fr] items-center gap-3 px-3 py-2">
      <dt className="text-[12px] text-faint">{label}</dt>
      <dd className="min-w-0 text-ink">{children}</dd>
    </div>
  );
}
