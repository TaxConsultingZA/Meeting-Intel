"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { X, FolderOpen, Loader2, CheckCircle2, Download, AlertCircle, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { getAvailableRecordings, getRecordingJobs, importRecording, reprocessRecording } from "@/lib/api";
import LocalDateTime from "./local-date-time";
import { UNVERIFIED_RECORDING_ASSOCIATION } from "@/lib/recording-identity";
import { cn } from "@/lib/utils";
import { compareRecordingTimes } from "@/lib/time";
import StateBadge from "./state-badge";
import { RECORDING_ACTION_CLASS, RECORDING_BADGE_CLASS } from "./recording-ui";
import { JobControls, recordingStatusMessage } from "./recording-jobs";
import type { AvailableRecording, ProcessingState, RecordingJobOut } from "@/lib/types";

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
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
  sent: "Email submission accepted",
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
  const tableRef = useRef<HTMLTableElement>(null);
  const [listHeight, setListHeight] = useState<number>();
  const [recordings, setRecordings] = useState<AvailableRecording[]>(initialRecordings ?? []);
  const [hasLoaded, setHasLoaded] = useState(initialRecordings !== null);
  const [refreshing, setRefreshing] = useState(initialRecordings === null);
  const [error, setError] = useState<string | null>(null);
  const [completeRead, setCompleteRead] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  useEffect(() => {
    const table = tableRef.current;
    if (!table) return;
    const rows = Array.from(table.tBodies[0]?.rows ?? []).slice(0, 7);
    const measure = () => setListHeight(Math.ceil((table.tHead?.getBoundingClientRect().height ?? 0)
      + rows.reduce((height, row) => height + row.getBoundingClientRect().height, 0)) + 1);
    const observer = new ResizeObserver(measure);
    rows.forEach(row => observer.observe(row));
    if (table.tHead) observer.observe(table.tHead);
    measure();
    return () => observer.disconnect();
  }, [recordings, hasLoaded]);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const jobsInFlight = useRef<Promise<RecordingJobOut[]> | null>(null);
  const actionInFlight = useRef(new Set<string>());
  const refreshInFlight = useRef(false);

  const readFailed = useCallback((cause: unknown) => {
    const unauthorized = typeof cause === "object" && cause !== null && "status" in cause && cause.status === 401;
    setCompleteRead(false);
    setAuthRequired(unauthorized);
    setError(unauthorized
      ? "Your session could not be verified. Sign in again to reload the list and task status."
      : "The list or task status could not be loaded. Saved data is retained; the latest information is not verified.");
  }, []);

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
    setCompleteRead(false);
    try {
      const [data, jobs] = await Promise.all([getAvailableRecordings(upn), loadJobs()]);
      setRecordings(data.map(rec => ({ ...rec, job: jobs.find(job => job.drive_item_id === rec.drive_item_id) })));
      setHasLoaded(true);
      setCompleteRead(true);
      setAuthRequired(false);
      setError(null);
    } catch (cause) {
      readFailed(cause);
    } finally {
      refreshInFlight.current = false;
      setRefreshing(false);
    }
  }, [loadJobs, upn, readFailed]);

  useEffect(() => {
    // Prefetched rows are immediately visible, but remain cached until both
    // saved-list and task-status reads succeed for this opening/session.
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

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
    if (!hasActiveJobs || authRequired) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      if (refreshInFlight.current) return;
      // A recovered status-only read cannot certify a failed list read.
      if (!completeRead) { void load(); return; }
      void refreshJobs().catch(readFailed);
    }, 5000);
    return () => clearInterval(timer);
  }, [hasActiveJobs, authRequired, completeRead, load, refreshJobs, readFailed]);

  async function handleImport(rec: AvailableRecording) {
    if (actionInFlight.current.has(rec.drive_item_id)) return;
    actionInFlight.current.add(rec.drive_item_id);
    setBusy((prev) => new Set(prev).add(rec.drive_item_id));
    try {
      await importRecording(rec.drive_item_id, rec.drive_id, upn);
      toast.success(`"${rec.original_filename || rec.name}" queued for processing`);
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
      toast.success(`"${rec.original_filename || rec.name}" requeued for processing`);
      await load();
    } catch {
      toast.error("We could not confirm the reprocess request. Refresh recordings to check the status before trying again.");
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
          <Loader2 size={13} aria-hidden="true" className="animate-spin" /> Queuing recording…
        </span>
      );
    }

    if (rec.job) {
      return <div className="flex items-center justify-end gap-2">
        <JobControls job={rec.job} token={upn} onChanged={refreshJobs} buttonClassName={RECORDING_ACTION_CLASS} />
        {rec.job.can_reprocess && <button
          type="button"
          onClick={() => handleReprocess(rec)}
          className={RECORDING_ACTION_CLASS}
        >Reprocess</button>}
        {rec.job.meeting_id && <Link href={`/meetings/${rec.job.meeting_id}`} onClick={onClose} className={RECORDING_ACTION_CLASS}>View</Link>}
      </div>;
    }

    if (!rec.already_imported) {
      return (
        <button
          type="button"
          onClick={() => handleImport(rec)}
          className={cn(RECORDING_ACTION_CLASS, "border-[#003366] bg-[#003366] text-white hover:bg-[#002244]")}
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
          className={RECORDING_ACTION_CLASS}
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
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
      >
        <div className="sticky top-0 z-10 flex shrink-0 items-center justify-between border-b bg-[#003366] px-6 py-4">
          <div>
            <h2 id="import-recording-title" className="text-white font-semibold text-[15px]">Process a Past Recording</h2>
            <p className="text-white/60 text-[13px] mt-0.5">
              Recordings · SAST
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close recording dialog" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-white hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-white">
            <X size={20} />
          </button>
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden">
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

          {hasLoaded && <p role="status" aria-label="Recording data freshness" className="shrink-0 mx-6 my-3 text-xs text-[#6b7280]">
            {completeRead ? "Recording list and task status loaded successfully." : "Showing cached recordings. Latest list and task status are not verified."}
          </p>}

          {error && !hasLoaded && (
            <div role="alert" className="flex flex-col items-center justify-center py-16 text-[#6b7280]">
              <AlertCircle size={36} className="mb-3 text-red-400" />
              <p className="text-[13.5px] font-semibold text-[#1a1a2e] mb-1">Could not load recordings</p>
              <p className="text-[12.5px] text-center max-w-xs">{error}</p>
              {authRequired && <Link href="/login" className="mt-3 text-sm font-semibold text-[#003366] underline">Sign in again</Link>}
              <button type="button" onClick={load} className="mt-4 text-[13px] text-[#003366] hover:underline font-medium">
                Try again
              </button>
            </div>
          )}

          {error && hasLoaded && (
            <div role="alert" className="shrink-0 mx-6 my-4 max-h-[25vh] overflow-auto rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-900">
              Refresh failed. Showing the previously loaded recordings. {error}
              {authRequired && <Link href="/login" className="ml-2 font-semibold underline">Sign in again</Link>}
            </div>
          )}

          {hasLoaded && !error && recordings.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-[#6b7280]">
              <FolderOpen size={36} className="mb-3 text-[#dde1e8]" />
              <p className="text-[13.5px] font-semibold text-[#1a1a2e] mb-1">No discovered recordings</p>
              <p className="text-[12.5px]">Use Update meetings and recordings on the dashboard to update this list.</p>
            </div>
          )}

          {hasLoaded && recordings.length > 0 && (
            <div role="region" aria-label="Recording list" tabIndex={0} className="min-h-0 overflow-auto overscroll-contain focus-visible:outline-2 focus-visible:outline-[#003366]" style={{ maxHeight: listHeight ?? "34rem" }}>
            <table ref={tableRef} className="w-full min-w-[920px] table-fixed text-sm">
              <colgroup>
                <col className="w-[26%]" /><col className="w-[20%]" /><col className="w-[8%]" />
                <col className="w-[13%]" /><col className="w-[15%]" /><col className="w-[18%]" />
              </colgroup>
              <thead className="sticky top-0 z-10">
                <tr>
                  {TABLE_HEADERS.map((h) => (
                    <th key={h} className="bg-[#f8fafc] text-[#374151] text-xs font-semibold px-4 py-2.5 text-left border-b border-[#dde1e8] first:pl-6 last:pr-6">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...recordings].sort((a, b) => compareRecordingTimes(a.created_at, b.created_at)).map((rec, i) => (
                  <tr key={rec.drive_item_id} className={i % 2 === 1 ? "bg-[#f8fafc]" : ""}>
                    <td className="px-4 py-3 pl-6 border-b border-[#dde1e8] font-medium text-[#1a1a2e] min-w-0">
                      <span tabIndex={0} className="block truncate text-[13px] focus:whitespace-normal focus:break-all hover:whitespace-normal hover:break-all" title={rec.original_filename || rec.name}>
                        {rec.original_filename || rec.name}
                      </span>
                      {rec.teams_meeting_verified && <span className="mt-0.5 block text-[11px] text-[#6b7280]">Teams meeting verified: {rec.teams_meeting_title}</span>}
                      {rec.calendar_matched === false && (
                        <span className="mt-0.5 block text-[11px] font-normal text-[#6b7280]">No calendar meeting linked</span>
                      )}
                      {rec.calendar_matched && rec.calendar_title && <span className="mt-0.5 block truncate text-[11px] font-normal text-[#6b7280]" title={rec.calendar_title}>Calendar event linked: {rec.calendar_title}</span>}
                      {rec.association_status === "needs_review" && <span className="block text-xs text-amber-800">{UNVERIFIED_RECORDING_ASSOCIATION}</span>}
                      {rec.identity_reason && rec.association_status !== "needs_review" && <span className="block text-xs text-[#6b7280]">{rec.identity_reason}</span>}
                      {rec.association_status === "independent" && <span className="block text-xs text-[#6b7280]">Independent recording</span>}
                      {rec.meeting_error && (
                        <span className="block text-[11px] text-red-500 truncate mt-0.5" title="Processing could not finish. Open the meeting for recovery options.">
                          Processing could not finish. Open the meeting for recovery options.
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                      <LocalDateTime value={rec.created_at} unavailable="Recording date unavailable" />
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                      {formatBytes(rec.size)}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[12.5px]">
                      {rec.job ? <span title={recordingStatusMessage(rec.job)}><StateBadge state={rec.job.processing_status} compact className={RECORDING_BADGE_CLASS} /></span> : rec.meeting_state ? (
                        <StateBadge state={(["awaiting_review", "approved", "sent"] as ProcessingState[]).includes(rec.meeting_state) ? "completed" : rec.meeting_state} compact className={RECORDING_BADGE_CLASS} />
                      ) : <span className={RECORDING_BADGE_CLASS+" bg-slate-100 text-slate-600"}>Not started</span>}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[12.5px]">
                      {rec.job?.review_status ? <StateBadge state={rec.job.review_status} compact className={RECORDING_BADGE_CLASS} />
                        : rec.meeting_state && (["awaiting_review", "approved", "sent"] as ProcessingState[]).includes(rec.meeting_state)
                          ? <StateBadge state={rec.meeting_state} compact className={RECORDING_BADGE_CLASS} /> : "—"}
                    </td>
                    <td className="px-4 py-3 pr-6 border-b border-[#dde1e8] text-right whitespace-nowrap">
                      {renderAction(rec)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>

        <div className="shrink-0 px-6 py-4 border-t border-[#dde1e8] flex items-center justify-end bg-[#f8fafc]">
          <div className="flex items-center gap-2">
            <button type="button" title="Reload recording list" onClick={() => void load()} disabled={refreshing} className={RECORDING_ACTION_CLASS}>
              {refreshing && <Loader2 size={13} className="animate-spin" />}{refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
