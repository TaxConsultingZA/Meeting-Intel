"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { X, FolderOpen, Loader2, CheckCircle2, Download, AlertCircle, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { getAvailableRecordings, getRecordingJobs, importRecording, reprocessRecording } from "@/lib/api";
import LocalDateTime from "./local-date-time";
import StateBadge from "./state-badge";
import { JobControls } from "./recording-jobs";
import type { AvailableRecording, ProcessingState, RecordingJobOut } from "@/lib/types";

function formatBytes(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const STATE_LABEL: Record<ProcessingState, string> = {
  queued: "Queued",
  downloading: "Downloading",
  transcribing: "Transcribing",
  extracting: "Extracting",
  awaiting_review: "Awaiting Review",
  approved: "Approved",
  sent: "Sent",
  failed: "Failed",
  cancelled: "Cancelled", cancel_requested: "Cancel requested", processing: "Processing", completed: "Completed",
};

const IN_PROGRESS: ProcessingState[] = ["queued", "downloading", "transcribing", "extracting"];
const TABLE_HEADERS = ["Recording", "Date", "Size", "Processing", "Review", "Actions"];

interface Props {
  upn: string;
  onClose: () => void;
  initialRecordings?: AvailableRecording[] | null;
  onRecordingsLoaded?: (recordings: AvailableRecording[]) => void;
}

export default function ImportModal({ upn, onClose, initialRecordings = null, onRecordingsLoaded }: Props) {
  const [recordings, setRecordings] = useState<AvailableRecording[]>(initialRecordings ?? []);
  const [hasLoaded, setHasLoaded] = useState(initialRecordings !== null);
  const [refreshing, setRefreshing] = useState(initialRecordings === null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const jobsInFlight = useRef<Promise<RecordingJobOut[]> | null>(null);
  const actionInFlight = useRef(new Set<string>());
  const refreshInFlight = useRef(false);

  const loadJobs = useCallback(() => {
    if (jobsInFlight.current) return jobsInFlight.current;
    const request = getRecordingJobs(upn).finally(() => {
      if (jobsInFlight.current === request) jobsInFlight.current = null;
    });
    jobsInFlight.current = request;
    return request;
  }, [upn]);

  const load = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    setRefreshing(true);
    setError(null);
    try {
      const [data, jobs] = await Promise.all([getAvailableRecordings(upn), loadJobs()]);
      setRecordings(data.map(rec => ({ ...rec, job: jobs.find(job => job.drive_item_id === rec.drive_item_id) })));
      setHasLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load recordings");
    } finally {
      refreshInFlight.current = false;
      setRefreshing(false);
    }
  }, [loadJobs, upn]);

  useEffect(() => {
    if (hasLoaded) return;
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [hasLoaded, load]);

  useEffect(() => {
    if (hasLoaded) onRecordingsLoaded?.(recordings);
  }, [hasLoaded, onRecordingsLoaded, recordings]);

  const refreshJobs = useCallback(async () => {
    const jobs = await loadJobs();
    setRecordings(previous => previous.map(rec => ({ ...rec, job: jobs.find(job => job.drive_item_id === rec.drive_item_id) })));
  }, [loadJobs]);
  const hasActiveJobs = recordings.some((rec) => rec.job && (
    rec.job.status === "pending" || rec.job.status === "processing" || rec.job.processing_status === "cancel_requested"
  ));
  useEffect(() => {
    if (!hasActiveJobs) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void refreshJobs().catch(() => setError("Recording status could not be refreshed."));
    }, 5000);
    return () => clearInterval(timer);
  }, [hasActiveJobs, refreshJobs]);

  async function handleImport(rec: AvailableRecording) {
    if (actionInFlight.current.has(rec.drive_item_id)) return;
    actionInFlight.current.add(rec.drive_item_id);
    setBusy((prev) => new Set(prev).add(rec.drive_item_id));
    try {
      await importRecording(rec.drive_item_id, rec.drive_id, upn);
      toast.success(`"${rec.name.replace(/\.mp4$/i, "")}" queued for processing`);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Import failed");
    } finally {
      actionInFlight.current.delete(rec.drive_item_id);
      setBusy((prev) => { const s = new Set(prev); s.delete(rec.drive_item_id); return s; });
    }
  }

  async function handleReprocess(rec: AvailableRecording) {
    if (actionInFlight.current.has(rec.drive_item_id)) return;
    if (!window.confirm("Reprocess this recording? The current review draft will remain available unless the new transcription and extraction finish successfully.")) return;
    actionInFlight.current.add(rec.drive_item_id);
    setBusy((prev) => new Set(prev).add(rec.drive_item_id));
    try {
      await reprocessRecording(rec.drive_item_id, rec.drive_id, upn);
      toast.success(`"${rec.name.replace(/\.mp4$/i, "")}" requeued for processing`);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reprocess failed");
    } finally {
      actionInFlight.current.delete(rec.drive_item_id);
      setBusy((prev) => { const s = new Set(prev); s.delete(rec.drive_item_id); return s; });
    }
  }

  function renderAction(rec: AvailableRecording) {
    const isBusy = busy.has(rec.drive_item_id);
    const state = rec.meeting_state;

    if (isBusy) {
      return (
        <span role="status" className="inline-flex items-center gap-1.5 text-[#6b7280] text-[12.5px]">
          <Loader2 size={13} className="animate-spin" /> Processing…
        </span>
      );
    }

    if (rec.job) {
      return <div className="flex items-center justify-end gap-2.5">
        <JobControls job={rec.job} token={upn} onChanged={refreshJobs} />
        {rec.job.can_reprocess && <button
          type="button"
          onClick={() => handleReprocess(rec)}
          className="inline-flex h-8 items-center rounded-md px-2 text-xs font-semibold text-blue-800 hover:bg-blue-50"
        >Reprocess</button>}
        {rec.job.meeting_id && <Link href={`/meetings/${rec.job.meeting_id}`} onClick={onClose} className="inline-flex h-8 items-center rounded-md px-2 text-xs font-semibold text-blue-800 hover:bg-blue-50">View</Link>}
      </div>;
    }

    if (!rec.already_imported) {
      return (
        <button
          type="button"
          onClick={() => handleImport(rec)}
          className="inline-flex h-8 items-center gap-1.5 rounded bg-[#003366] px-3 text-[12.5px] font-semibold text-white transition-colors hover:bg-[#0a4a8c]"
        >
          <Download size={13} /> Transcribe
        </button>
      );
    }

    if (state && (["awaiting_review", "approved", "sent"] as ProcessingState[]).includes(state) && rec.meeting_id) {
      return (
        <Link
          href={`/meetings/${rec.meeting_id}`}
          onClick={onClose}
          className="inline-flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 text-white text-[12.5px] font-semibold px-3 py-1.5 rounded transition-colors"
        >
          <ExternalLink size={13} /> View
        </Link>
      );
    }

    if (state && IN_PROGRESS.includes(state)) {
      return (
        <span className="inline-flex items-center gap-1.5 text-blue-600 text-[12.5px] font-medium">
          <Loader2 size={13} className="animate-spin" /> {STATE_LABEL[state]}
        </span>
      );
    }

    return (
      <span className="inline-flex items-center gap-1 text-green-600 text-[12.5px] font-medium">
        <CheckCircle2 size={14} /> {state ? STATE_LABEL[state] : "Imported"}
      </span>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-recording-title"
        className="w-full max-w-5xl overflow-hidden rounded-lg bg-white shadow-xl"
      >
        <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-6 py-5 flex items-center justify-between">
          <div>
            <h2 id="import-recording-title" className="text-white font-semibold text-[15px]">Process a Past Recording</h2>
            <p className="text-white/60 text-[13px] mt-0.5">
              View or process MP4 recordings from your OneDrive Recordings folder
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-white/60 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-auto">
          {refreshing && !hasLoaded && (
            <div role="status" aria-label="Loading recordings" className="min-h-72 animate-pulse" aria-live="polite">
              <span className="sr-only">Loading recordings…</span>
              <div className="grid grid-cols-[2fr_1fr_0.7fr_1fr_1fr_1fr] border-b border-[#dde1e8] bg-[#f8fafc] px-6 py-3">
                {TABLE_HEADERS.map((header) => (
                  <div key={header} className="text-xs font-semibold text-[#374151]">{header}</div>
                ))}
              </div>
              {[0, 1, 2, 3].map((row) => (
                <div key={row} className="grid grid-cols-[2fr_1fr_0.7fr_1fr_1fr_1fr] items-center gap-4 border-b border-[#eef1f4] px-6 py-4">
                  <div className="h-3 w-3/4 rounded bg-slate-200" />
                  <div className="h-3 w-4/5 rounded bg-slate-200" />
                  <div className="h-3 w-2/3 rounded bg-slate-200" />
                  <div className="h-5 w-16 rounded-full bg-slate-200" />
                  <div className="h-5 w-14 rounded-full bg-slate-200" />
                  <div className="ml-auto h-7 w-20 rounded bg-slate-200" />
                </div>
              ))}
            </div>
          )}

          {error && !hasLoaded && (
            <div className="flex flex-col items-center justify-center py-16 text-[#6b7280]">
              <AlertCircle size={36} className="mb-3 text-red-400" />
              <p className="text-[13.5px] font-semibold text-[#1a1a2e] mb-1">Could not load recordings</p>
              <p className="text-[12.5px] text-center max-w-xs">{error}</p>
              <button type="button" onClick={load} className="mt-4 text-[13px] text-[#003366] hover:underline font-medium">
                Try again
              </button>
            </div>
          )}

          {error && hasLoaded && (
            <div role="alert" className="mx-6 mt-4 rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-900">
              Refresh failed. Showing the previously loaded recordings. {error}
            </div>
          )}

          {hasLoaded && recordings.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-[#6b7280]">
              <FolderOpen size={36} className="mb-3 text-[#dde1e8]" />
              <p className="text-[13.5px] font-semibold text-[#1a1a2e] mb-1">No recordings found</p>
              <p className="text-[12.5px]">Your OneDrive Recordings folder appears to be empty.</p>
            </div>
          )}

          {hasLoaded && recordings.length > 0 && (
            <table className="w-full min-w-[920px] table-fixed text-sm">
              <colgroup>
                <col className="w-[28%]" /><col className="w-[15%]" /><col className="w-[8%]" />
                <col className="w-[13%]" /><col className="w-[13%]" /><col className="w-[23%]" />
              </colgroup>
              <thead>
                <tr>
                  {TABLE_HEADERS.map((h) => (
                    <th key={h} className="bg-[#f8fafc] text-[#374151] text-xs font-semibold px-4 py-2.5 text-left border-b border-[#dde1e8] first:pl-6 last:pr-6">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recordings.map((rec, i) => (
                  <tr key={rec.drive_item_id} className={i % 2 === 1 ? "bg-[#f8fafc]" : ""}>
                    <td className="px-4 py-3 pl-6 border-b border-[#dde1e8] font-medium text-[#1a1a2e] max-w-50">
                      <span className="block truncate text-[13px]" title={rec.name}>
                        {rec.name.replace(/\.mp4$/i, "")}
                      </span>
                      {rec.meeting_error && (
                        <span className="block text-[11px] text-red-500 truncate mt-0.5" title={rec.meeting_error}>
                          {rec.meeting_error}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                      <LocalDateTime value={rec.created_at} />
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                      {formatBytes(rec.size)}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[12.5px]">
                      {rec.job ? <StateBadge state={rec.job.processing_status} /> : rec.meeting_state ? (
                        <span className={`font-medium ${rec.meeting_state === "failed" ? "text-red-600" : rec.meeting_state === "awaiting_review" ? "text-amber-600" : "text-[#6b7280]"}`}>
                          {(["awaiting_review", "approved", "sent"] as ProcessingState[]).includes(rec.meeting_state) ? "Completed" : STATE_LABEL[rec.meeting_state]}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[12.5px]">
                      {rec.job?.review_status ? <StateBadge state={rec.job.review_status} />
                        : rec.meeting_state && (["awaiting_review", "approved", "sent"] as ProcessingState[]).includes(rec.meeting_state)
                          ? <StateBadge state={rec.meeting_state} /> : "—"}
                    </td>
                    <td className="px-4 py-3 pr-6 border-b border-[#dde1e8] text-right whitespace-nowrap">
                      {renderAction(rec)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#dde1e8] flex items-center justify-between bg-[#f8fafc]">
          <p className="text-[12px] text-[#6b7280]">
            The transcript and AI notes will appear for organiser review once processing finishes.
          </p>
          <div className="flex items-center gap-4">
            <button type="button" onClick={() => void load()} disabled={refreshing} className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[13px] font-semibold text-[#003366] hover:bg-[#eaf0f6] disabled:cursor-not-allowed disabled:opacity-50">
              {refreshing && <Loader2 size={13} className="animate-spin" />}{refreshing ? "Refreshing…" : "Refresh"}
            </button>
            <button type="button" onClick={onClose} className="inline-flex h-8 items-center rounded-md px-2 text-[13px] font-semibold text-[#003366] hover:bg-[#eaf0f6]">
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
