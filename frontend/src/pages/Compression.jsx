import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Film, Image, Play, TriangleAlert } from "lucide-react";
import { api } from "../services/api.js";
import { useScan } from "../context/scan.jsx";
import { useToast } from "../hooks/useToast.jsx";
import { isActive, useJobs } from "../hooks/useJobs.js";
import { Button } from "../components/ui/button.jsx";
import { Badge, Card, EmptyState, Notice, PageHeader, SkeletonRows } from "../components/ui/primitives.jsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/controls.jsx";
import { JobStatus, StagePills } from "../components/ui/progress.jsx";
import { DriveFileLinks } from "../components/GoogleLinks.jsx";
import { formatBytes, formatDuration, formatMbps } from "../utils/format.js";

const CONF_TONE = { High: "ok", Medium: "warn", Low: "neutral" };
const CATEGORY_LABEL = { video: "Video", images: "Image", pdf: "PDF" };

export default function Compression() {
  const [data, setData] = useState(null);
  const [working, setWorking] = useState(null);
  const [completed, setCompleted] = useState([]); // finished this session: estimate vs actual
  const { version } = useScan();
  const toast = useToast();

  const load = useCallback(async () => {
    const [files, videos, suggestions] = await Promise.all([
      api.getCompressionCandidates(), api.getVideoCandidates(), api.getSuggestions(),
    ]);
    setData({ files, videos, suggestions });
    return { videos, suggestions };
  }, []);

  function recordResult(name, estimated, res) {
    if (res?.success) setCompleted((prev) => [{ name, estimated, ...res }, ...prev].slice(0, 10));
  }

  // Video compression (and rule suggestions) run as background jobs, keyed by Drive file id.
  const { jobs, track } = useJobs(async (key, job) => {
    const res = job.result;
    const name = job.payload?.file_name || "File";
    if (job.status === "failed") toast(job.error || "Compression failed.", "error");
    else if (res?.success) toast(`${name} compressed — saved ${formatBytes(res.saved_bytes)} (${res.reduction_percent}%).`);
    else toast(res?.message || "No meaningful saving, so the original was kept.", "error");
    const estimate = data?.videos.candidates.find((c) => c.drive_id === key)?.estimated_saving_bytes;
    recordResult(name, estimate, res);
    await load();
  });

  useEffect(() => {
    load()
      .then(async ({ videos, suggestions }) => {
        videos.candidates.forEach((c) => c.job && track(c.drive_id, c.job));
        const queued = suggestions.filter((s) => s.status === "queued" && s.job_id);
        const fetched = await Promise.all(queued.map((s) => api.getJob(s.job_id).catch(() => null)));
        fetched.forEach((job, i) => isActive(job) && track(queued[i].drive_id, job));
      })
      .catch((e) => toast(e.message, "error"));
  }, [load, track, version, toast]);

  async function compressNow(c) {
    setWorking(c.file_id);
    try {
      const res = await api.compressFile(c.file_id);
      toast(res.message, res.success ? "success" : "error");
      recordResult(c.name, c.estimated_saving_bytes, res);
      await load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setWorking(null);
    }
  }

  async function startJob(key, request) {
    setWorking(key);
    try {
      track(key, await request());
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setWorking(null);
    }
  }

  if (!data) return <Card bodyClassName="p-0"><SkeletonRows rows={8} /></Card>;
  const { files, videos, suggestions } = data;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Compression"
        description="Each file is replaced in place by a smaller version — same file ID, link, sharing and folder. The original stays restorable from History; if Drive keeps it “forever”, CloudClean deletes it after 30 days (or sooner with Free space now)."
      />

      {completed.length > 0 && (
        <Card title="Completed this session" subtitle="Estimated before vs. measured after." bodyClassName="p-0">
          <table className="w-full text-[13px]">
            <thead className="border-b border-line">
              <tr><th className="th">File</th><th className="th text-right">Before</th><th className="th text-right">After</th><th className="th text-right">Estimated</th><th className="th text-right">Actual saved</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {completed.map((c, i) => (
                <tr key={i}>
                  <td className="td max-w-[300px] truncate font-medium">{c.name}</td>
                  <td className="td mono text-right text-sub">{formatBytes(c.original_size_bytes)}</td>
                  <td className="td mono text-right text-sub">{formatBytes(c.new_size_bytes)}</td>
                  <td className="td mono text-right text-faint">{c.estimated ? formatBytes(c.estimated) : "—"}</td>
                  <td className="td mono text-right text-ok-ink">{formatBytes(c.saved_bytes)} ({c.reduction_percent}%)</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Tabs defaultValue={videos.candidates.length || !files.length ? "videos" : "files"}>
        <TabsList>
          <TabsTrigger value="videos" count={videos.candidates.length}>Video queue</TabsTrigger>
          <TabsTrigger value="files" count={files.length}>Images & PDFs</TabsTrigger>
          <TabsTrigger value="rules" count={suggestions.length}>Rule suggestions</TabsTrigger>
        </TabsList>

        <TabsContent value="videos" className="mt-4 space-y-4">
          {!videos.ffmpeg_available && (
            <Notice tone="warn" icon={TriangleAlert}>ffmpeg isn't installed on the worker, so videos can't be re-encoded yet (README → Video compression).</Notice>
          )}
          <Card bodyClassName="p-0">
            {videos.candidates.length === 0 ? (
              <EmptyState icon={Film} title="No videos to compress" subtitle="See below for why each video isn't suggested." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead className="border-b border-line">
                    <tr>
                      <th className="th">Video</th><th className="th">Format</th><th className="th">Bitrate → H.264 target</th>
                      <th className="th text-right">Size</th><th className="th text-right">Est. saving</th><th className="th" />
                    </tr>
                  </thead>
                  {videos.candidates.map((c) => {
                    const job = jobs[c.drive_id];
                    const running = isActive(job);
                    return (
                      <tbody key={c.file_id} className="border-b border-line last:border-b-0">
                        <tr className="align-top">
                          <td className="td max-w-[260px] py-2">
                            <div className="truncate font-medium">{c.name}</div>
                            <Badge tone={CONF_TONE[c.confidence_label]} className="mt-1">{c.confidence_label} confidence</Badge>
                          </td>
                          <td className="td mono py-2 text-sub">
                            <div>{c.width}×{c.height}</div>
                            <div className="text-[12px] text-faint">{formatDuration(c.duration_s)}</div>
                          </td>
                          <td className="td mono py-2 text-sub">
                            <div>{formatMbps(c.current_kbps)}</div>
                            <div className="text-[12px] text-faint">→ {formatMbps(c.target_kbps)}</div>
                          </td>
                          <td className="td mono py-2 text-right">{formatBytes(c.current_size_bytes)}</td>
                          <td className="td mono py-2 text-right text-ok-ink">{formatBytes(c.estimated_saving_bytes)}</td>
                          <td className="td py-2">
                            <div className="flex items-center justify-end gap-1">
                              <DriveFileLinks file={c} />
                              <Button
                                variant="primary"
                                size="sm"
                                disabled={running || working === c.drive_id || !videos.ffmpeg_available}
                                onClick={() => startJob(c.drive_id, () => api.compressVideo(c.file_id))}
                              >
                                <Play className="h-3.5 w-3.5" /> {running ? "Running" : "Compress"}
                              </Button>
                            </div>
                          </td>
                        </tr>
                        {running && (
                          <tr>
                            <td colSpan={6} className="px-3 pb-3">
                              <div className="space-y-1.5 rounded border border-line bg-canvas p-2.5">
                                <StagePills job={job} />
                                <JobStatus job={job} />
                              </div>
                            </td>
                          </tr>
                        )}
                      </tbody>
                    );
                  })}
                </table>
              </div>
            )}
          </Card>

          {videos.not_suggested?.length > 0 && (
            <Card bodyClassName="p-0">
              <details open={videos.candidates.length === 0} className="group">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-[13px] font-medium text-ink">
                  <ChevronRight className="h-4 w-4 text-faint transition-transform group-open:rotate-90" />
                  Not suggested — why? <span className="mono text-faint">{videos.not_suggested.length}</span>
                </summary>
                <ul className="divide-y divide-line border-t border-line">
                  {videos.not_suggested.map((v) => (
                    <li key={v.file_id} className="flex items-start justify-between gap-4 px-4 py-2.5">
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium text-ink">{v.name}</div>
                        <div className="mt-0.5 text-[12px] text-sub">{v.reason}</div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="mono text-[13px] text-sub">{formatBytes(v.size_bytes)}</span>
                        <DriveFileLinks file={v} />
                      </div>
                    </li>
                  ))}
                </ul>
              </details>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="files" className="mt-4">
          <Card bodyClassName="p-0">
            {files.length === 0 ? (
              <EmptyState icon={Image} title="No images or PDFs to compress" subtitle="Nothing reaches your minimum saving (Settings). Files already tried aren't suggested again unless they change." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead className="border-b border-line">
                    <tr>
                      <th className="th">File</th><th className="th">Method</th><th className="th">Confidence</th>
                      <th className="th text-right">Current</th><th className="th text-right">Estimated</th>
                      <th className="th text-right">Saving</th><th className="th" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {files.map((c) => (
                      <tr key={c.file_id}>
                        <td className="td max-w-[300px] truncate font-medium">{c.name}</td>
                        <td className="td mono text-[12px] text-sub">{c.method}</td>
                        <td className="td"><Badge tone={CONF_TONE[c.confidence_label]}>{c.confidence_label}</Badge></td>
                        <td className="td mono text-right">{formatBytes(c.current_size_bytes)}</td>
                        <td className="td mono text-right text-sub">{formatBytes(c.estimated_optimized_size_bytes)}</td>
                        <td className="td mono text-right text-ok-ink">{formatBytes(c.estimated_saving_bytes)}</td>
                        <td className="td">
                          <div className="flex items-center justify-end gap-1">
                            <DriveFileLinks file={c} />
                            <Button variant="primary" size="sm" disabled={working === c.file_id} onClick={() => compressNow(c)}>
                              {working === c.file_id ? "Compressing…" : "Compress"}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="rules" className="mt-4">
          <Card
            title="Suggested by your rules"
            subtitle="Files your nightly auto-compression rules matched. Nothing happens until you compress one."
            action={<Link to="/settings" className="text-[12px] font-medium text-accent-ink hover:underline">Manage rules →</Link>}
            bodyClassName="p-0"
          >
            {suggestions.length === 0 ? (
              <EmptyState title="No rule suggestions" subtitle="Create a rule in Settings, e.g. videos over 200 MB not modified in 90 days." />
            ) : (
              <ul className="divide-y divide-line">
                {suggestions.map((s) => {
                  const job = jobs[s.drive_id];
                  const running = isActive(job) || s.status === "queued";
                  return (
                    <li key={s.id} className="space-y-2 px-4 py-2.5">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-[13px] font-medium text-ink">{s.file_name}</div>
                          <div className="text-[12px] text-sub">
                            {CATEGORY_LABEL[s.category] || s.category} · <span className="mono">{formatBytes(s.size_bytes)}</span> · could save ~
                            <span className="mono">{formatBytes(s.estimated_saving_bytes)}</span>
                          </div>
                        </div>
                        {!running && (
                          <div className="flex gap-1">
                            <Button variant="ghost" size="sm" onClick={() => api.dismissSuggestion(s.id).then(load, (e) => toast(e.message, "error"))}>Dismiss</Button>
                            <Button variant="primary" size="sm" disabled={working === s.drive_id} onClick={() => startJob(s.drive_id, () => api.applySuggestion(s.id))}>Compress</Button>
                          </div>
                        )}
                      </div>
                      {isActive(job) && <JobStatus job={job} />}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
