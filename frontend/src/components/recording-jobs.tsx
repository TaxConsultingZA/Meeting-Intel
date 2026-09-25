"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { cancelRecordingJob, getRecordingJobs, retryRecordingJob } from "@/lib/api";
import type { RecordingJobOut } from "@/lib/types";
import StateBadge from "./state-badge";

export function JobControls({ job, token, onChanged }: { job: RecordingJobOut; token: string; onChanged: () => void | Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  async function act(action: "retry" | "cancel") {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const result = await (action === "retry" ? retryRecordingJob : cancelRecordingJob)(job.job_id, token);
      toast.success(result.status === "cancel_requested" ? "Cancellation requested; waiting for the current operation to stop." : action === "retry" ? "Recording queued for retry." : "Recording cancelled.");
      await onChanged();
    } catch (error) { toast.error(error instanceof Error ? error.message : "Recording operation failed"); }
    finally { busyRef.current = false; setBusy(false); }
  }
  return <div className="flex items-center gap-3 text-xs font-semibold">
    {job.can_retry && <button disabled={busy} onClick={() => act("retry")} className="inline-flex items-center gap-1 text-blue-800 disabled:cursor-not-allowed disabled:opacity-50">{busy && <Loader2 size={12} className="animate-spin" />} {busy ? "Retrying…" : "Retry"}</button>}
    {job.can_cancel && <button disabled={busy} onClick={() => act("cancel")} className="inline-flex items-center gap-1 text-red-700 disabled:cursor-not-allowed disabled:opacity-50">{busy && !job.can_retry && <Loader2 size={12} className="animate-spin" />} {busy ? "Working…" : "Cancel"}</button>}
  </div>;
}

export default function RecordingJobs({ token, meetingId, onChanged }: { token: string; meetingId?: string; onChanged?: () => void | Promise<void> }) {
  const [jobs, setJobs] = useState<RecordingJobOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshInFlight = useRef(false);
  const refresh = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    try { setJobs(await getRecordingJobs(token, meetingId)); setError(null); }
    catch { setError("Recording status is temporarily unavailable."); }
    finally { refreshInFlight.current = false; setLoading(false); }
  }, [token, meetingId]);
  const hasActiveJobs = jobs.some((job) =>
    job.status === "pending" || job.status === "processing" || job.processing_status === "cancel_requested"
  );
  useEffect(() => {
    const first = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(first);
  }, [refresh]);
  useEffect(() => {
    if (!hasActiveJobs) return;
    const timer = setInterval(() => {
      if (document.visibilityState !== "hidden") void refresh();
    }, 10000);
    return () => clearInterval(timer);
  }, [hasActiveJobs, refresh]);
  if (!loading && !jobs.length && !error) return null;
  return <section aria-label="Recording processing" className="mb-5 rounded-lg border border-blue-200 bg-white p-4">
    <h2 className="font-semibold text-[#003366] mb-2">Recording processing</h2>
    {loading && <p role="status" className="text-sm text-[#6b7280]">Loading recording status…</p>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {jobs.map(job => <div key={job.job_id} className="border-t py-3 text-sm space-y-2">
      {!meetingId && (job.meeting_id ? <Link className="font-medium underline" href={`/meetings/${job.meeting_id}`}>{job.title}</Link> : <p>{job.title}</p>)}
      <StateBadge state={job.processing_status} />
      {job.processing_status === "completed" && job.review_status && <div className="flex items-center gap-1 text-xs text-[#6b7280]">Review: <StateBadge state={job.review_status} /></div>}
      {job.processing_status === "queued" && !job.processing_enabled && <p className="text-xs text-amber-800">Queued — processing is paused in staging. No paid transcription will run.</p>}
      {job.processing_status === "cancel_requested" && <p className="text-xs text-amber-800">Waiting for the current operation to stop. Saved data will be kept.</p>}
      {job.error && <p className="text-xs text-red-700">{job.error}</p>}
      <JobControls job={job} token={token} onChanged={async () => { await refresh(); await onChanged?.(); }} />
    </div>)}
  </section>;
}
