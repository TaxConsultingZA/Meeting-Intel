"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { cancelRecordingJob, getRecordingJobs, retryRecordingJob } from "@/lib/api";
import type { RecordingJobOut } from "@/lib/types";
import StateBadge from "./state-badge";

export function JobControls({ job, token, onChanged }: { job: RecordingJobOut; token: string; onChanged: () => void | Promise<void> }) {
  const [busy, setBusy] = useState(false);
  async function act(action: "retry" | "cancel") {
    setBusy(true);
    try {
      const result = await (action === "retry" ? retryRecordingJob : cancelRecordingJob)(job.job_id, token);
      toast.success(result.status === "cancel_requested" ? "Cancellation requested; waiting for the current operation to stop." : action === "retry" ? "Recording queued for retry." : "Recording cancelled.");
      await onChanged();
    } catch (error) { toast.error(error instanceof Error ? error.message : "Recording operation failed"); }
    finally { setBusy(false); }
  }
  return <div className="flex gap-3 text-xs font-semibold">
    {job.can_retry && <button disabled={busy} onClick={() => act("retry")} className="text-blue-800 disabled:opacity-50">Retry</button>}
    {job.can_cancel && <button disabled={busy} onClick={() => act("cancel")} className="text-red-700 disabled:opacity-50">Cancel</button>}
    {busy && <span role="status">Working…</span>}
  </div>;
}

export default function RecordingJobs({ token, meetingId, onChanged }: { token: string; meetingId?: string; onChanged?: () => void | Promise<void> }) {
  const [jobs, setJobs] = useState<RecordingJobOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try { setJobs(await getRecordingJobs(token, meetingId)); setError(null); }
    catch { setError("Recording status is temporarily unavailable."); }
  }, [token, meetingId]);
  useEffect(() => {
    const first = setTimeout(() => void refresh(), 0);
    const timer = setInterval(() => void refresh(), 5000);
    return () => { clearTimeout(first); clearInterval(timer); };
  }, [refresh]);
  if (!jobs.length && !error) return null;
  return <section aria-label="Recording processing" className="mb-5 rounded-lg border border-blue-200 bg-white p-4">
    <h2 className="font-semibold text-[#003366] mb-2">Recording processing</h2>
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
