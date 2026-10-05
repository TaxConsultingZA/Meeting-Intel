"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { cancelRecordingJob, getRecordingJobs, reprocessRecordingJob, retryRecordingJob } from "@/lib/api";
import type { RecordingJobOut } from "@/lib/types";
import StateBadge from "./state-badge";

function recordingStatusMessage(job: RecordingJobOut): string {
  switch (job.processing_status) {
    case "completed":
      if (job.review_status === "sent") return "Processing is complete. Approved notes have been emailed.";
      if (job.review_status === "approved") return "Processing is complete. Meeting notes have been approved.";
      if (job.review_status === "awaiting_review") return "Processing is complete. Meeting notes are ready for review.";
      return "Recording processing is complete.";
    case "failed": return "Processing stopped before this attempt could finish. Previously saved results have been kept.";
    case "cancelled": return "Processing was cancelled. Previously saved meeting data has been kept.";
    case "cancel_requested": return "Cancellation is pending. Waiting for the current operation to stop; saved data will be kept.";
    case "queued": return job.processing_enabled
      ? "Waiting for processing to start. Status updates automatically."
      : "Processing is paused in staging. No paid transcription will run.";
    case "downloading": return "Preparing the recording for transcription.";
    case "transcribing": return "Converting the recording into a speaker-labelled transcript.";
    case "extracting": return "Preparing the transcript and meeting notes for review.";
    default: return "Processing is underway. Status updates automatically.";
  }
}

export function JobControls({ job, token, onChanged, showReprocess = false }: { job: RecordingJobOut; token: string; onChanged: () => void | Promise<void>; showReprocess?: boolean }) {
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  async function act(action: "retry" | "cancel" | "reprocess") {
    if (busyRef.current) return;
    if (action === "reprocess" && !window.confirm("Reprocess this recording? The current review draft will remain available unless the new transcription and extraction finish successfully.")) return;
    busyRef.current = true;
    setBusy(true);
    try {
      if (action === "reprocess") {
        await reprocessRecordingJob(job.job_id, token);
        toast.success("Recording queued for reprocessing. Previous results stay available until replacement succeeds.");
      } else {
        const result = await (action === "retry" ? retryRecordingJob : cancelRecordingJob)(job.job_id, token);
        toast.success(result.status === "cancel_requested" ? "Cancellation requested. Processing has not stopped yet; waiting for the current operation to finish." : action === "retry" ? "Retry queued. Recording status will update when processing starts." : "Recording cancelled. Previously saved meeting data has been kept.");
      }
      await onChanged();
    } catch (error) { toast.error(error instanceof Error ? error.message : "Recording operation failed"); }
    finally { busyRef.current = false; setBusy(false); }
  }
  return <div className="flex flex-wrap items-center gap-2 text-xs font-semibold" aria-busy={busy}>
    {job.can_retry && <button type="button" disabled={busy} onClick={() => act("retry")} className="inline-flex min-h-8 items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-blue-800 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50">{busy && <Loader2 size={12} className="animate-spin" />} {busy ? "Retrying…" : "Retry"}</button>}
    {job.can_cancel && <button type="button" disabled={busy} onClick={() => act("cancel")} className="inline-flex min-h-8 items-center gap-1 rounded-md border border-red-200 px-2.5 py-1.5 text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50">{busy && !job.can_retry && <Loader2 size={12} className="animate-spin" />} {busy ? "Working…" : "Cancel"}</button>}
    {showReprocess && job.can_reprocess && <button type="button" disabled={busy} onClick={() => act("reprocess")} className="inline-flex min-h-8 items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-blue-800 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50">{busy && <Loader2 size={12} className="animate-spin" />} {busy ? "Reprocessing…" : "Reprocess"}</button>}
  </div>;
}

export default function RecordingJobs({ token, meetingId, onChanged, onTerminalTransition }: { token: string; meetingId?: string; onChanged?: () => void | Promise<void>; onTerminalTransition?: () => void | Promise<void> }) {
  const [jobs, setJobs] = useState<RecordingJobOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshInFlight = useRef(false);
  const previousJobs = useRef<{ token: string; meetingId?: string; jobs: Map<string, RecordingJobOut> } | null>(null);
  const refresh = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    try {
      const nextJobs = await getRecordingJobs(token, meetingId);
      const previous = previousJobs.current;
      const sameScope = previous?.token === token && previous.meetingId === meetingId;
      const latestByRecording = new Map<string, RecordingJobOut>();
      let terminalTransition = false;
      for (const job of nextJobs) {
        // The API lists newest first; keep one latest attempt per recording.
        if (latestByRecording.has(job.drive_item_id)) continue;
        latestByRecording.set(job.drive_item_id, job);
        const oldJob = sameScope ? previous.jobs.get(job.drive_item_id) : undefined;
        if (oldJob && ["completed", "failed", "cancelled"].includes(job.status)
          && (oldJob.status === "pending" || oldJob.status === "processing" || oldJob.job_id !== job.job_id)) {
          terminalTransition = true;
        }
      }
      previousJobs.current = { token, meetingId, jobs: latestByRecording };
      setJobs(nextJobs);
      setError(null);
      if (terminalTransition) await onTerminalTransition?.();
    }
    catch { setError("Recording status is temporarily unavailable."); }
    finally { refreshInFlight.current = false; setLoading(false); }
  }, [token, meetingId, onTerminalTransition]);
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
  return <section aria-label="Recording processing" className="mb-5 overflow-hidden rounded-lg border border-blue-200 bg-white">
    <div className="border-b border-blue-100 bg-blue-50/50 px-5 py-4">
      <h2 className="font-semibold text-[#003366]">Recording processing</h2>
      <p className="mt-1 text-xs text-[#6b7280]">Track processing separately from meeting review and email delivery.</p>
    </div>
    <div className="space-y-4 p-5">
    {loading && <p role={meetingId ? undefined : "status"} aria-live="polite" className="flex items-center gap-2 text-sm text-[#6b7280]"><Loader2 size={16} className="animate-spin" aria-hidden="true" />Loading recording status…</p>}
    {error && <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-semibold">Unable to refresh recording status</p>
      <p className="mt-1 text-xs">{error} {jobs.length > 0 ? "Showing the last available status." : meetingId ? "Meeting information remains available below." : "Try refreshing to load recording jobs."}</p>
      <button type="button" onClick={() => void refresh()} className="mt-2 rounded-md border border-amber-300 px-3 py-1.5 text-xs font-semibold hover:bg-amber-100">Refresh status</button>
    </div>}
    {!loading && !jobs.length && !error && <div className="rounded-md border border-dashed border-[#dde1e8] bg-[#fafbfc] p-4 text-sm text-[#6b7280]">
      <p className="font-medium text-[#374151]">No recording job status available</p>
      <p className="mt-1 text-xs">{meetingId ? "Check the meeting status below for any saved results." : "Recording jobs will appear here when available."}</p>
    </div>}
    {jobs.map(job => <div key={job.job_id} className={`rounded-lg border p-4 text-sm ${job.status === "failed" ? "border-red-200 bg-red-50/30" : job.status === "completed" ? "border-green-200 bg-green-50/30" : "border-[#dde1e8]"}`}>
      {!meetingId && (job.meeting_id ? <Link className="mb-3 block font-semibold text-[#003366] underline" href={`/meetings/${job.meeting_id}`}>{job.title}</Link> : <p className="mb-3 font-semibold text-[#003366]">{job.title}</p>)}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-semibold text-[#6b7280]">Current recording status</p>
          <StateBadge state={job.processing_status} />
          <p className="mt-2 text-xs leading-5 text-[#374151]">{recordingStatusMessage(job)}</p>
        </div>
        <div>
          <p className="mb-2 text-xs font-semibold text-[#6b7280]">Current review status</p>
          {job.review_status ? <StateBadge state={job.review_status} /> : <p className="text-xs text-[#6b7280]">{meetingId ? "See meeting details below for saved review results." : "No review status available for this job."}</p>}
        </div>
      </div>
      {job.error && <div className="mt-3 rounded-md border border-red-100 bg-red-50 p-3 text-xs leading-5 text-red-800"><p className="font-semibold">{job.status === "cancelled" ? "Cancellation details" : "What happened"}</p><p className="mt-1 break-words">{job.error}</p></div>}
      {job.status === "failed" && <p role="alert" className="mt-3 text-xs leading-5 text-red-800">{job.can_retry ? "Use Retry below to queue another attempt." : "Retry is not available for this job. Contact an administrator for help."}</p>}
      {job.status === "cancelled" && job.can_retry && <p className="mt-3 text-xs text-[#6b7280]">Use Retry to queue another attempt when you are ready.</p>}
      <div className="mt-4 border-t border-[#dde1e8] pt-3">
        <p className="mb-2 text-xs font-semibold text-[#6b7280]">Available actions</p>
        <JobControls job={job} token={token} showReprocess onChanged={async () => { await refresh(); await onChanged?.(); }} />
        {!job.can_retry && !job.can_cancel && !job.can_reprocess && <p className="text-xs text-[#6b7280]">{job.processing_status === "cancel_requested" ? "Cancellation is pending. No further action is needed." : "No recording actions are available for your account in this state."}</p>}
        {job.can_reprocess && <p className="mt-2 text-xs leading-5 text-[#6b7280]">Reprocess creates a fresh transcript and meeting notes. Previous results stay available until replacement succeeds.</p>}
      </div>
    </div>)}
    </div>
  </section>;
}
