import { useSearchParams } from "react-router-dom";
import { CircleCheck, FlaskConical, KeyRound, LogOut, TriangleAlert } from "lucide-react";
import { useAccountActions } from "../hooks/useAccountActions.js";
import { CONNECT_ERRORS } from "../pages/Connect.jsx";
import { Button } from "./ui/button.jsx";
import { Badge, Card, Notice } from "./ui/primitives.jsx";

/** Settings → Account: what this session is connected to, and how to switch. */
export default function AccountCard() {
  const { user, status, busy, connectGoogle, startDemo, signOut } = useAccountActions();
  const [params] = useSearchParams();
  const error = params.get("error") ? CONNECT_ERRORS[params.get("error")] || "Something went wrong." : null;
  const demo = user?.is_demo;

  return (
    <section id="account" className="scroll-mt-4 space-y-3">
      {error && <Notice tone="bad" icon={TriangleAlert}>{error}</Notice>}
      <Card title="Account" subtitle="Switching to another account or to Demo Mode never shows the previous account's data.">
        <dl className="divide-y divide-line rounded border border-line text-[13px]">
          <Row label="Signed in as"><span className="mono">{user?.email}</span></Row>
          <Row label="Mode">
            {demo ? <Badge tone="warn"><FlaskConical className="h-3 w-3" /> Demo Mode — simulated Drive</Badge>
              : <Badge tone="ok"><CircleCheck className="h-3 w-3" /> Google Drive connected</Badge>}
          </Row>
          <Row label="Google sign-in on this server">
            {status ? (status.google_configured ? <Badge tone="ok">Set up</Badge> : <Badge tone="bad">Not set up</Badge>) : "—"}
          </Row>
        </dl>
        {status && !status.google_configured && (
          <Notice tone="warn" icon={TriangleAlert} className="mt-3">{CONNECT_ERRORS.not_configured}</Notice>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" disabled={!status?.google_configured} onClick={connectGoogle}>
            <KeyRound className="h-3.5 w-3.5" /> {demo ? "Connect Google account" : "Reconnect Google account"}
          </Button>
          <Button onClick={startDemo} disabled={busy}>
            <FlaskConical className="h-3.5 w-3.5" /> {demo ? "Start a new demo" : "Try Demo Mode"}
          </Button>
          <Button variant="ghost" onClick={signOut}><LogOut className="h-3.5 w-3.5" /> Sign out</Button>
        </div>
      </Card>
    </section>
  );
}

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[minmax(0,180px)_1fr] items-center gap-3 px-3 py-2">
      <dt className="text-[12px] text-faint">{label}</dt>
      <dd className="min-w-0 truncate text-ink">{children}</dd>
    </div>
  );
}
