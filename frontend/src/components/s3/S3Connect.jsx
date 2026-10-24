import { useState } from "react";
import { FlaskConical, KeyRound } from "lucide-react";
import { s3Api } from "../../services/s3Api.js";
import { Button } from "../ui/button.jsx";
import { Card } from "../ui/primitives.jsx";
import { Field } from "../ui/controls.jsx";

const REGIONS = ["ap-south-1", "us-east-1", "us-east-2", "us-west-2", "ap-southeast-1", "eu-west-1", "eu-central-1"];

export default function S3Connect({ onConnected, toast }) {
  const [accessKeyId, setAccessKeyId] = useState("");
  const [secret, setSecret] = useState("");
  const [region, setRegion] = useState("ap-south-1");
  const [busy, setBusy] = useState(false);
  const [policy, setPolicy] = useState(null);

  async function run(fn) {
    setBusy(true);
    try {
      onConnected(await fn());
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={<span className="flex items-center gap-2"><FlaskConical className="h-4 w-4 text-warn" /> S3 demo account</span>} subtitle="Four simulated buckets with typical waste. Nothing real is touched.">
        <ul className="space-y-1 text-[12px] text-sub">
          <li>· Logs and backups never moved out of S3 Standard</li>
          <li>· Hundreds of GB of noncurrent object versions</li>
          <li>· Abandoned multipart uploads, duplicate uploads, oversized images</li>
        </ul>
        <Button variant="primary" className="mt-4" disabled={busy} onClick={() => run(s3Api.connectDemo)}>
          Start S3 demo
        </Button>
      </Card>

      <Card title={<span className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-accent-ink" /> Connect an AWS account</span>} subtitle="An IAM user limited to the permissions below. Keys are checked with AWS STS, then stored encrypted.">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            run(() => s3Api.connect(accessKeyId, secret, region));
          }}
        >
          <Field label="Access key ID"><input className="field mono" value={accessKeyId} onChange={(e) => setAccessKeyId(e.target.value)} autoComplete="off" required /></Field>
          <Field label="Secret access key"><input className="field mono" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password" required /></Field>
          <Field label="Default region">
            <select className="field mono" value={region} onChange={(e) => setRegion(e.target.value)}>
              {REGIONS.map((r) => <option key={r}>{r}</option>)}
            </select>
          </Field>
          <div className="flex items-center gap-2">
            <Button type="submit" variant="primary" disabled={busy}>{busy ? "Checking…" : "Connect"}</Button>
            <Button variant="ghost" onClick={async () => setPolicy(policy ? null : JSON.stringify(await s3Api.iamPolicy(), null, 2))}>
              {policy ? "Hide" : "Show"} IAM policy
            </Button>
          </div>
        </form>
        {policy && <pre className="mt-3 max-h-72 overflow-auto rounded border border-line bg-canvas p-3 text-[11px] text-ink">{policy}</pre>}
      </Card>
    </div>
  );
}
