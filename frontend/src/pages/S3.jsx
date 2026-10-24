import { useCallback, useEffect, useState } from "react";
import { Database, Unplug } from "lucide-react";
import { useToast } from "../hooks/useToast.jsx";
import { useScan } from "../context/scan.jsx";
import { s3Api } from "../services/s3Api.js";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, PageHeader, SkeletonRows } from "../components/ui/primitives.jsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/controls.jsx";
import { ConfirmDialog } from "../components/ui/dialog.jsx";
import S3Connect from "../components/s3/S3Connect.jsx";
import S3Overview from "../components/s3/S3Overview.jsx";
import { S3Compression, S3Duplicates, S3History } from "../components/s3/S3Lists.jsx";
import { formatDateTime } from "../utils/format.js";

export default function S3() {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("overview");
  const [disconnecting, setDisconnecting] = useState(false);
  const { s3Version, runS3, s3Scanning } = useScan();
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      setData(await s3Api.overview());
    } catch (e) {
      toast(e.message, "error");
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load, s3Version]);

  if (!data) return <Card bodyClassName="p-0"><SkeletonRows rows={8} /></Card>;

  return (
    <div className="space-y-4">
      <PageHeader
        title="AWS S3 Manager"
        description="Every bucket priced by storage class, then lifecycle tiering, version and upload cleanup, duplicate removal and compression — previewed first and undoable."
        actions={
          data.connected && (
            <Button variant="ghost" onClick={() => setDisconnecting(true)}>
              <Unplug className="h-3.5 w-3.5" /> Disconnect
            </Button>
          )
        }
      />

      {!data.connected ? (
        <S3Connect
          toast={toast}
          onConnected={(o) => {
            setData(o);
            runS3();
          }}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-sub">
            {data.is_demo ? <Badge tone="warn">S3 demo account</Badge> : <span>Account <span className="mono text-ink">{data.account_id}</span></span>}
            <span className="text-faint">·</span>
            <span>{data.last_scan_at ? <>Last scanned <span className="mono">{formatDateTime(data.last_scan_at)}</span></> : "Not scanned yet"}</span>
          </div>

          {!data.last_scan_at ? (
            <Card>
              <EmptyState
                icon={Database}
                title="No scan yet"
                subtitle="Listing costs one request per 1,000 objects."
                action={<Button variant="primary" disabled={s3Scanning} onClick={runS3}>Scan buckets</Button>}
              />
            </Card>
          ) : (
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList>
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="duplicates">Duplicates</TabsTrigger>
                <TabsTrigger value="compression">Compression</TabsTrigger>
                <TabsTrigger value="history">S3 History</TabsTrigger>
              </TabsList>
              <TabsContent value="overview" className="mt-4">
                <S3Overview data={data} onChanged={load} onOpenTab={setTab} toast={toast} />
              </TabsContent>
              <TabsContent value="duplicates" className="mt-4">
                <S3Duplicates toast={toast} onChanged={load} version={s3Version} />
              </TabsContent>
              <TabsContent value="compression" className="mt-4">
                <S3Compression toast={toast} onChanged={load} version={s3Version} />
              </TabsContent>
              <TabsContent value="history" className="mt-4">
                <S3History toast={toast} onChanged={load} version={s3Version} />
              </TabsContent>
            </Tabs>
          )}
        </>
      )}

      <ConfirmDialog
        open={disconnecting}
        title="Disconnect this AWS account?"
        consequences={[
          { kind: "info", text: "CloudClean forgets the stored keys and the cached scan. Nothing in your buckets changes." },
          { kind: "undoable", text: "Lifecycle rules CloudClean added stay in place — undo them from S3 History first if you want them gone." },
        ]}
        confirmLabel="Disconnect"
        onConfirm={async () => {
          await s3Api.disconnect();
          setDisconnecting(false);
          setTab("overview");
          await load();
        }}
        onCancel={() => setDisconnecting(false)}
      />
    </div>
  );
}
