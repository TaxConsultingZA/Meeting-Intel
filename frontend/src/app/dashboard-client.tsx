"use client";
import Link from "next/link";
import LoadingSpinner from "@/components/loading-spinner";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Calendar, Users, ChevronRight, Upload, Mic, Video, Share2, Power } from "lucide-react";
import StateBadge from "@/components/state-badge";
import LocalDateTime, { useUserTimeZone } from "@/components/local-date-time";
import { formatEventTime, parseInstant } from "@/lib/time";
import ImportModal from "@/components/import-modal";
import RecentMeetings from "@/components/recent-meetings";
import { JobControls, recordingStatusMessage } from "@/components/recording-jobs";
import { decideRecordingProcessing, getAllMeetings, getHistoricalMeetings, getProcessingRequests, getRecordingJobs, getSyncStatus, getUpcomingMeetings, requestHistoricalAccess, requestMeetingEditAccess, shareMeeting, syncCalendarsNow, unsubscribeCurrentUser, getCalendarSyncRun, waitForCalendarSync, CalendarSyncUnconfirmedError } from "@/lib/api";
import type { CalendarSyncResult } from "@/lib/api";
import type { AvailableRecording, MeetingOut, ProcessingState, CalendarEvent, SyncState, RecordingJobOut, RecordingProcessingRequest } from "@/lib/types";

/** Convert a UPN like "jane.doe@taxconsulting.co.za" to a display name "Jane Doe". */
function formatUpn(upn: string | null | undefined): string {
  if (!upn) return "";
  return upn.split("@")[0].split(".").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

const PIPELINE_STATES: ProcessingState[] = ["queued", "downloading", "transcribing", "extracting"];

function calendarSyncMessage(result: CalendarSyncResult) {
  if (result.status === "success") return "Calendar sync succeeded.";
  return `Calendar sync ${result.status === "partial" ? "partially completed" : "failed"}. Some calendars could not be read. Check existing Microsoft access and subscription status, then use Sync calendar now to try again.`;
}

interface Props {
  meetings: MeetingOut[];
  recordingJobs?: RecordingJobOut[];
  upcoming: CalendarEvent[];
  historical: MeetingOut[];
  upn: string;
  accessToken: string;
  isSubscribed: boolean;
  isAdmin?: boolean;
  syncStates: SyncState[];
  loadErrors: string[];
  deferInitialLoad?: boolean;
}

type Tab = "upcoming" | "recent" | "in_progress" | "review" | "old_meetings" | "cancelled";

function conciseMicrosoftError(error: string): string {
  const lower = error.toLowerCase();
  const source = lower.includes("onedrive") || lower.includes("/drive")
    ? "OneDrive"
    : lower.includes("calendar")
      ? "Calendar"
      : "Microsoft data";

  if (lower.includes("403") || lower.includes("forbidden")) {
    return `${source} permission is unavailable (Microsoft Graph returned 403).`;
  }
  if (lower.includes("401") || lower.includes("unauthorized")) {
    return `${source} authorization is unavailable (Microsoft Graph returned 401).`;
  }
  if (lower.includes("404") || lower.includes("not found")) {
    return `${source} could not be found (Microsoft Graph returned 404).`;
  }
  return error.length > 180 ? `${error.slice(0, 177)}...` : error;
}

export default function DashboardClient({ meetings: initialMeetings, recordingJobs: initialRecordingJobs = [], upcoming: initialUpcoming, historical: initialHistorical, upn, accessToken, isSubscribed, isAdmin = false, syncStates: initialSyncStates, loadErrors: initialLoadErrors, deferInitialLoad = false }: Props) {
  const router = useRouter();
  const [meetings, setMeetings] = useState(initialMeetings);
  const [recordingJobs, setRecordingJobs] = useState(initialRecordingJobs);
  const [processingRequests, setProcessingRequests] = useState<RecordingProcessingRequest[]>([]);
  const [processingRequestsError, setProcessingRequestsError] = useState("");
  const [processingRequestBusy, setProcessingRequestBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("upcoming");
  const [hasOpenedRecent, setHasOpenedRecent] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [availableRecordings, setAvailableRecordings] = useState<AvailableRecording[] | null>(null);
  const [historical, setHistorical] = useState<MeetingOut[]>(initialHistorical);
  const [historicalLoading, setHistoricalLoading] = useState(false);
  const [historicalError, setHistoricalError] = useState("");
  const historicalLoaded = useRef(initialHistorical.length > 0);
  const historicalLoadInFlight = useRef(false);
  const [upcoming, setUpcoming] = useState<CalendarEvent[]>(initialUpcoming);
  const [syncStates, setSyncStates] = useState<SyncState[]>(initialSyncStates);
  const [meetingLoadErrors, setMeetingLoadErrors] = useState(initialLoadErrors);
  const [recordingJobLoadErrors, setRecordingJobLoadErrors] = useState<string[]>([]);
  const [syncLoadErrors, setSyncLoadErrors] = useState<string[]>([]);
  const [calendarLoadErrors, setCalendarLoadErrors] = useState<string[]>([]);
  const [pollingError, setPollingError] = useState("");
  const [refreshingProcessing, setRefreshingProcessing] = useState(false);
  const [loading, setLoading] = useState({
    meetings: deferInitialLoad,
    recordingJobs: deferInitialLoad,
    sync: deferInitialLoad,
    calendar: deferInitialLoad && isSubscribed,
  });
  const [shareModal, setShareModal] = useState<{ meetingId: string; title: string } | null>(null);
  const [unsubscribing, setUnsubscribing] = useState(false);
  const pollingInFlight = useRef(false);
  const calendarSyncInFlight = useRef(false);
  const calendarDisplayVersion = useRef(0);
  const [calendarSyncing, setCalendarSyncing] = useState(false);
  const [calendarSyncBlocked, setCalendarSyncBlocked] = useState(isAdmin && isSubscribed);
  const [calendarStatusVersion, setCalendarStatusVersion] = useState(0);
  const calendarObserver = useRef<AbortController | null>(null);
  const [calendarSyncFeedback, setCalendarSyncFeedback] = useState<{ message: string; failed: boolean } | null>(null);
  const [calendarRefreshKey, setCalendarRefreshKey] = useState(0);

  useEffect(() => {
    if (!calendarSyncFeedback || calendarSyncFeedback.failed) return;
    const timer = setTimeout(() => setCalendarSyncFeedback(null), 60_000);
    return () => clearTimeout(timer);
  }, [calendarSyncFeedback]);

  useEffect(() => {
    if (!isAdmin || !isSubscribed) return;
    const observer = new AbortController();
    calendarObserver.current = observer;
    void (async () => {
      try {
        const run = await getCalendarSyncRun(accessToken, undefined, observer.signal);
        if (observer.signal.aborted) return;
        if (!run) { setCalendarSyncBlocked(false); return; }
        const wasPending = run.status === "queued" || run.status === "running";
        calendarSyncInFlight.current = true;
        setCalendarSyncing(run.status === "queued" || run.status === "running");
        const result = await waitForCalendarSync(accessToken, run, observer.signal);
        if (observer.signal.aborted) return;
        setCalendarSyncBlocked(!run.retry_allowed && run.status === "unknown");
        // Completed history is not evidence that a new sync just succeeded.
        if (wasPending || result.status !== "success") {
          setCalendarSyncFeedback({ failed: result.status !== "success", message: calendarSyncMessage(result) });
        }
        // A terminal history entry predates this mount's initial reads. Only a
        // run observed in flight needs a second refresh when it completes.
        if (!wasPending) return;
        ++calendarDisplayVersion.current;
        setCalendarRefreshKey((version) => version + 1);
        setLoading((current) => ({ ...current, calendar: true, sync: true }));
        void getUpcomingMeetings(accessToken).then((events) => {
          if (!observer.signal.aborted) { setUpcoming(events); setCalendarLoadErrors([]); }
        }).catch(() => {
          if (!observer.signal.aborted) setCalendarLoadErrors(["Calendar display could not be refreshed. Reload to try again."]);
        }).finally(() => {
          if (!observer.signal.aborted) setLoading((current) => ({ ...current, calendar: false }));
        });
        void getSyncStatus(accessToken).then((states) => {
          if (!observer.signal.aborted) { setSyncStates(states); setSyncLoadErrors([]); }
        }).catch(() => {
          if (!observer.signal.aborted) setSyncLoadErrors(["Sync status could not be refreshed. Reload to try again."]);
        }).finally(() => {
          if (!observer.signal.aborted) setLoading((current) => ({ ...current, sync: false }));
        });
      } catch (error) {
        if (!observer.signal.aborted) setCalendarSyncFeedback({ failed: true,
          message: error instanceof CalendarSyncUnconfirmedError ? error.message
            : "Calendar sync outcome is unconfirmed; some changes may already be saved. Check sync status without starting another sync.",
        });
      } finally {
        if (!observer.signal.aborted) {
          calendarSyncInFlight.current = false;
          setCalendarSyncing(false);
        }
      }
    })();
    return () => { observer.abort(); calendarObserver.current?.abort(); calendarSyncInFlight.current = false; };
  }, [accessToken, isAdmin, isSubscribed, calendarStatusVersion]);
  const hasActiveProcessing = recordingJobs.some((job) =>
    job.status === "pending" || job.status === "processing" || job.processing_status === "cancel_requested"
  ) || meetings.some((meeting) => PIPELINE_STATES.includes(meeting.state));

  useEffect(() => {
    if (!deferInitialLoad) return;

    let cancelled = false;
    const publishErrors = { meetings: setMeetingLoadErrors, recordingJobs: setRecordingJobLoadErrors, sync: setSyncLoadErrors, calendar: setCalendarLoadErrors };
    const load = async <T,>(promise: Promise<T>, label: string, apply: (data: T) => void, category: keyof typeof publishErrors) => {
      const version = calendarDisplayVersion.current;
      const currentRequest = () => !cancelled && (
        (category !== "calendar" && category !== "sync") || version === calendarDisplayVersion.current
      );
      setLoading((current) => ({ ...current, [category]: true }));
      try {
        const data = await promise;
        if (currentRequest()) {
          apply(data);
          publishErrors[category]([]);
        }
      } catch (error) {
        const detail = error instanceof Error ? error.message : "Unknown error";
        if (currentRequest()) publishErrors[category]([`${label}: ${detail}`]);
      } finally {
        if (currentRequest()) setLoading((current) => ({ ...current, [category]: false }));
      }
    };

    void load(getAllMeetings(accessToken), "Meeting records could not be loaded", setMeetings, "meetings");
    void load(getSyncStatus(accessToken), "Sync status could not be loaded", setSyncStates, "sync");
    void load(getRecordingJobs(accessToken, undefined, 20), "Recording status could not be loaded. Refresh to try again.", setRecordingJobs, "recordingJobs");
    if (isSubscribed) {
      void load(getUpcomingMeetings(accessToken), "Calendar sync failed", setUpcoming, "calendar");
    }
    return () => { cancelled = true; calendarDisplayVersion.current += 1; };
  }, [accessToken, deferInitialLoad, isSubscribed]);

  const refreshProcessing = useCallback(async () => {
    if (pollingInFlight.current || document.visibilityState === "hidden") return;
    pollingInFlight.current = true;
    setRefreshingProcessing(true);
    try {
      const results = await Promise.allSettled([
        getRecordingJobs(accessToken).then(setRecordingJobs),
        getAllMeetings(accessToken).then(setMeetings),
      ]);
      if (results.some((result) => result.status === "rejected")) throw new Error("Refresh incomplete");
      setPollingError("");
    } catch (error) {
      setPollingError("Live updates are temporarily unavailable. Your last loaded meeting and recording information is still shown.");
      throw error;
    } finally {
      pollingInFlight.current = false;
      setRefreshingProcessing(false);
    }
  }, [accessToken]);

  useEffect(() => {
    if (!hasActiveProcessing || showImport) return;
    const timer = setInterval(() => {
      void refreshProcessing().catch(() => {});
    }, 10000);
    return () => clearInterval(timer);
  }, [hasActiveProcessing, refreshProcessing, showImport]);

  const refreshProcessingRequests = useCallback(async () => {
    try {
      setProcessingRequests(await getProcessingRequests(accessToken));
      setProcessingRequestsError("");
    } catch {
      setProcessingRequestsError("Recording processing requests are temporarily unavailable.");
    }
  }, [accessToken]);

  useEffect(() => {
    let active = true;
    void getProcessingRequests(accessToken).then((requests) => {
      if (!active) return;
      setProcessingRequests(requests);
      setProcessingRequestsError("");
    }).catch(() => {
      if (active) setProcessingRequestsError("Recording processing requests are temporarily unavailable.");
    });
    return () => { active = false; };
  }, [accessToken]);

  async function refreshRecordingJobs() {
    await refreshProcessing();
  }

  async function handleCalendarSync() {
    if (!isAdmin || !isSubscribed || calendarSyncBlocked || calendarSyncInFlight.current) return;
    calendarSyncInFlight.current = true;
    setCalendarSyncing(true);
    setCalendarSyncFeedback(null);
    const observer = new AbortController();
    calendarObserver.current = observer;
    try {
      const result = await syncCalendarsNow(accessToken, observer.signal);
      if (observer.signal.aborted) return;
      setCalendarSyncFeedback({
        failed: result.status !== "success",
        message: calendarSyncMessage(result),
      });
      // Refresh each display independently; a slow read does not repeat the sync.
      const version = ++calendarDisplayVersion.current;
      setCalendarRefreshKey((current) => current + 1);
      setLoading((current) => ({ ...current, calendar: true, sync: true }));
      void getUpcomingMeetings(accessToken).then((events) => {
        if (version !== calendarDisplayVersion.current) return;
        setUpcoming(events);
        setCalendarLoadErrors([]);
      }).catch(() => {
        if (version === calendarDisplayVersion.current) setCalendarLoadErrors(["Calendar sync finished, but the calendar display could not be refreshed. Use Refresh or reload the page."]);
      }).finally(() => {
        if (version === calendarDisplayVersion.current) setLoading((current) => ({ ...current, calendar: false }));
      });
      void getSyncStatus(accessToken).then((states) => {
        if (version !== calendarDisplayVersion.current) return;
        setSyncStates(states);
        setSyncLoadErrors([]);
      }).catch(() => {
        if (version === calendarDisplayVersion.current) setSyncLoadErrors(["Sync status could not be refreshed. Reload the page to check the latest result."]);
      }).finally(() => {
        if (version === calendarDisplayVersion.current) setLoading((current) => ({ ...current, sync: false }));
      });
    } catch (error) {
      if (observer.signal.aborted) return;
      setCalendarSyncBlocked(true);
      setCalendarSyncFeedback({ failed: true,
        message: error instanceof CalendarSyncUnconfirmedError ? error.message
          : "Calendar sync could not be confirmed. Check sync status and existing Microsoft access; some changes may already be saved. Do not submit again until the outcome is known.",
      });
    } finally {
      if (!observer.signal.aborted) {
        calendarSyncInFlight.current = false;
        setCalendarSyncing(false);
      }
    }
  }

  function selectTab(nextTab: Tab) {
    if (nextTab === "recent") setHasOpenedRecent(true);
    if (nextTab === "old_meetings" && !historicalLoaded.current && !historicalLoadInFlight.current) {
      historicalLoadInFlight.current = true;
      setHistoricalLoading(true);
      setHistoricalError("");
      void getHistoricalMeetings(accessToken)
        .then((data) => {
          setHistorical(data);
          historicalLoaded.current = true;
        })
        .catch(() => setHistoricalError("Historical meetings could not be loaded."))
        .finally(() => {
          historicalLoadInFlight.current = false;
          setHistoricalLoading(false);
        });
    }
    setTab(nextTab);
  }

  async function handleOptOut() {
    if (!confirm("Turn off future Calendar and OneDrive processing? Existing meeting records will remain available.")) return;
    setUnsubscribing(true);
    try {
      await unsubscribeCurrentUser(accessToken);
      router.refresh();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Could not turn off processing");
    } finally {
      setUnsubscribing(false);
    }
  }

  // Preserve the existing wall-clock filter on every render without adding a timer.
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();
  const upcomingEvents  = upcoming.filter((e) => {
    if (e.status !== "upcoming") return false;
    const end = parseInstant(e.end);
    return !end || end.getTime() > now;
  });
  const inProgressEvents = upcoming.filter((e) => e.status === "in_progress");
  const activeRecordingJobs = recordingJobs.filter((job) =>
    job.status === "pending" || job.status === "processing" || job.processing_status === "cancel_requested"
  );
  const activeJobMeetingIds = new Set(activeRecordingJobs.flatMap((job) => job.meeting_id ? [job.meeting_id] : []));
  const pipelineActive  = meetings.filter((m) => PIPELINE_STATES.includes(m.state) && !activeJobMeetingIds.has(m.id));
  const pendingReview   = meetings.filter((m) => m.state === "awaiting_review");
  const pendingProcessingRequests = processingRequests.filter((request) => request.status === "pending");
  const oldMeetings     = meetings.filter((m) => m.state === "approved" || m.state === "sent");
  const cancelled       = meetings.filter((m) => m.state === "failed" || m.state === "cancelled");
  const persistedSyncErrors = syncStates
    .filter((state) => state.status === "failed")
    .map((state) => `${state.source === "onedrive" ? "OneDrive" : "Calendar"}: ${state.last_error ?? "Last sync failed"}`);
  // Prefer errors from this page load. Stored sync failures are a fallback and
  // must not duplicate the same Microsoft failure in the warning panel.
  const microsoftErrors = Array.from(new Set(calendarLoadErrors.map(conciseMicrosoftError)));
  const syncErrors = Array.from(new Set(
    [...syncLoadErrors, ...persistedSyncErrors].map(conciseMicrosoftError),
  ));

  async function handleRequestAccess(meetingId: string, accessType: "view" | "edit") {
    try {
      await requestHistoricalAccess(meetingId, accessToken, accessType);
      setHistorical((prev) => prev.map((m) => m.id === meetingId
        ? { ...m, edit_access_status: "pending", access_request_type: accessType }
        : m));
      alert(`${accessType === "view" ? "View" : "View and edit"} access requested. The meeting organiser will review it.`);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Could not request access");
    }
  }

  async function handleRequestMeetingEditAccess(meetingId: string) {
    await requestMeetingEditAccess(meetingId, accessToken);
    alert("Edit access requested. The meeting organiser will review it.");
  }

  const calendarLoading = isSubscribed && loading.calendar;
  const inProgressIncomplete = calendarLoading || loading.recordingJobs || loading.meetings
    || calendarLoadErrors.length > 0 || recordingJobLoadErrors.length > 0 || meetingLoadErrors.length > 0;
  const meetingsIncomplete = loading.meetings || meetingLoadErrors.length > 0;
  const stats: { icon: string; num: number; label: string; color: string; tab: Tab; loading: boolean }[] = [
    { icon: "📅", num: upcomingEvents.length,                  label: "Upcoming",         color: "bg-blue-50",   tab: "upcoming", loading: calendarLoading },
    { icon: "⚙️", num: inProgressEvents.length + activeRecordingJobs.length + pipelineActive.length, label: "In Progress", color: "bg-indigo-50", tab: "in_progress", loading: loading.meetings || loading.recordingJobs || calendarLoading },
    { icon: "📋", num: pendingReview.length + pendingProcessingRequests.length, label: "Awaiting Review", color: "bg-amber-50", tab: "review", loading: loading.meetings },
    { icon: "✅", num: oldMeetings.length,                     label: "Completed",        color: "bg-green-50",  tab: "old_meetings", loading: loading.meetings },
  ];

  return (
    <main className="max-w-5xl mx-auto px-6 py-7">
      {microsoftErrors.length > 0 && (
        <div role="alert" className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <p className="font-semibold">Microsoft data is temporarily unavailable</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">
            {microsoftErrors.map((error) => <li key={error}>{error}</li>)}
          </ul>
          <p className="mt-2 text-xs">No meetings are hidden as an empty result; try again after the permission or service issue is resolved.</p>
        </div>
      )}
      {meetingLoadErrors.length > 0 && (
        <div role="alert" className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <p className="font-semibold">Meeting data is temporarily unavailable</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">{meetingLoadErrors.map((error) => <li key={error}>{error}</li>)}</ul>
        </div>
      )}
      {recordingJobLoadErrors.length > 0 && (
        <div role="alert" className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">Recording status is temporarily unavailable</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">{recordingJobLoadErrors.map((error) => <li key={error}>{error}</li>)}</ul>
        </div>
      )}
      {syncErrors.length > 0 && (
        <div role="alert" className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">Sync status is temporarily unavailable</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">{syncErrors.map((error) => <li key={error}>{error}</li>)}</ul>
        </div>
      )}
      {pollingError && <div role="status" aria-live="polite" aria-label="Dashboard refresh status" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
        <p className="min-w-0 flex-1">{pollingError}</p>
        <button type="button" disabled={refreshingProcessing} onClick={() => { void refreshProcessing().catch(() => {}); }}
          className="rounded-md border border-amber-300 bg-white px-3 py-2 font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#003366] disabled:cursor-wait disabled:opacity-60">
          {refreshingProcessing ? "Retrying…" : "Retry refresh"}
        </button>
      </div>}
      <div className="mb-6 grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:gap-x-6">
        <div className="min-w-0">
          <h1 className="text-[22px] font-bold text-[#003366]">Meeting Intelligence</h1>
          <p className="text-[#6b7280] text-[13.5px] mt-0.5">
            Review and approve AI-extracted meeting notes before they are emailed to participants.
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2 [&>button]:shrink-0 [&>button]:whitespace-nowrap lg:justify-end">
          {isAdmin && isSubscribed && (
            <button type="button" onClick={() => void handleCalendarSync()} disabled={calendarSyncing || calendarSyncBlocked}
              title="Sync calendars for active Microsoft-linked subscribers; does not process recordings"
              className="inline-flex items-center gap-2 rounded-md border border-[#003366] bg-white px-3 py-2 text-[13px] font-semibold text-[#003366] disabled:opacity-50">
              {calendarSyncing && <span aria-hidden="true" className="h-3.5 w-3.5 rounded-full border-2 border-current border-r-transparent motion-safe:animate-spin" />}
              {calendarSyncing ? "Syncing calendars…" : "Sync calendar now"}
            </button>
          )}
          {isSubscribed && (
            <button
              type="button"
              onClick={handleOptOut}
              disabled={unsubscribing}
              title="Stop future Calendar and OneDrive processing; keep existing records"
              className="inline-flex items-center gap-2 rounded-md border border-[#003366] bg-white px-3 py-2 text-[13px] font-semibold text-[#003366] transition-colors hover:bg-blue-50 disabled:opacity-50"
            >
              <Power size={14} /> {unsubscribing ? "Turning off..." : "Opt out"}
            </button>
          )}
          <button
            type="button"
            onClick={() => isSubscribed && setShowImport(true)}
            disabled={!isSubscribed}
            title={isSubscribed ? "Process a past OneDrive recording" : "Opt in to process Calendar and OneDrive recordings"}
            className="inline-flex items-center gap-2 rounded-md bg-[#003366] px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-[#0a4a8c] disabled:cursor-not-allowed disabled:opacity-45"
          >
            <Upload size={15} /> {isSubscribed ? "Process Past Recording" : "Opt in to process recordings"}
          </button>
        </div>
      </div>

      {calendarSyncFeedback && <p role={calendarSyncFeedback.failed ? "alert" : "status"}
        className={calendarSyncFeedback.failed
          ? "mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          : "mb-4 text-sm text-[#003366]"}>
        {calendarSyncFeedback.message}
      </p>}
      {calendarSyncBlocked && !calendarSyncing && isAdmin && isSubscribed && (
        <button type="button" className="mb-4 rounded-md border px-3 py-2 text-sm"
          onClick={() => { setCalendarSyncBlocked(true); setCalendarStatusVersion((version) => version + 1); }}>Check sync status</button>
      )}

      {showImport && <ImportModal
        upn={accessToken}
        initialRecordings={availableRecordings}
        onRecordingsLoaded={setAvailableRecordings}
        onClose={() => {
        setShowImport(false);
        void refreshProcessing().catch(() => {});
      }} />}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-7">
        {stats.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => selectTab(s.tab)}
            className={`bg-white rounded-lg border shadow-sm p-4 flex items-center gap-3 text-left transition-all hover:shadow-md hover:-translate-y-0.5 ${
              tab === s.tab ? "border-[#003366]" : "border-[#dde1e8] hover:border-[#003366]"
            }`}
          >
            <div className={`w-10 h-10 ${s.color} rounded-lg flex items-center justify-center text-lg shrink-0`}>
              {s.icon}
            </div>
            <div>
              <div className="text-[22px] font-bold text-[#003366] leading-none" aria-busy={s.loading}>{s.num}</div>
              <div className="text-[12px] text-[#6b7280] mt-0.5">{s.label}</div>
            </div>
          </button>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap border-b-2 border-[#dde1e8] mb-6 gap-0">
        {([
          { id: "recent" as Tab, label: "Meetings", count: null },
          { id: "upcoming"    as Tab, label: "Upcoming Meetings",         count: upcomingEvents.length                          },
          { id: "in_progress" as Tab, label: "In Progress",               count: inProgressEvents.length + activeRecordingJobs.length + pipelineActive.length },
          { id: "review"      as Tab, label: "Awaiting Review",           count: pendingReview.length + pendingProcessingRequests.length },
          { id: "old_meetings"as Tab, label: "Old Meetings",               count: null                                          },
          { id: "cancelled"   as Tab, label: "Failed / Cancelled",                 count: cancelled.length || null                      },
        ]).map(({ id, label, count }) => (
          <button
            key={id}
            type="button"
            onClick={() => selectTab(id)}
            className={`px-4 py-2.5 text-[13px] font-medium border-b-2 -mb-0.5 transition-colors whitespace-nowrap ${
              tab === id
                ? "text-[#003366] border-[#C9A52C] font-semibold"
                : "text-[#6b7280] border-transparent hover:text-[#003366]"
            }`}
          >
            {label}
            {count !== null && count > 0 && (
              <span className="ml-1.5 bg-[#C9A52C] text-[#003366] text-[11px] font-bold px-1.5 py-0.5 rounded-full">
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {!calendarSyncing && (Object.values(loading).some(Boolean) || historicalLoading) && (
        <LoadingSpinner label="Dashboard loading" />
      )}
      {/* Upcoming Meetings */}
      {hasOpenedRecent && (
        <div hidden={tab !== "recent"}>
          <RecentMeetings
            token={accessToken}
            cacheIdentity={upn}
            isSubscribed={isSubscribed}
            refreshKey={calendarRefreshKey}
            historical={historical}
            processingRequests={processingRequests}
            onRefreshProcessingRequests={refreshProcessingRequests}
            onRequestHistoricalAccess={handleRequestAccess}
            onRequestMeetingEditAccess={handleRequestMeetingEditAccess}
          />
        </div>
      )}
      {tab === "upcoming" && (
        calendarLoading && upcomingEvents.length === 0
          ? null
          : upcomingEvents.length === 0
          ? calendarLoadErrors.length === 0 && <EmptyState
              icon="📅"
              title={isSubscribed ? "No upcoming meetings" : "Calendar processing is off"}
              sub={isSubscribed
                ? "No Teams meetings scheduled in the next 7 days."
                : "Opt in above to let Meeting Intelligence check your Outlook calendar and OneDrive recordings."}
            />
          : <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {upcomingEvents.map((ev) => <CalendarCard key={ev.event_id} event={ev} />)}
            </div>
      )}

      {/* In Progress */}
      {tab === "in_progress" && (
        inProgressEvents.length === 0 && activeRecordingJobs.length === 0 && pipelineActive.length === 0
          ? !inProgressIncomplete && <EmptyState icon="⚙️" title="Nothing in progress" sub="Meetings currently happening or being processed will appear here." />
          : <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {inProgressEvents.map((ev) => <CalendarCard key={ev.event_id} event={ev} inProgress />)}
              {activeRecordingJobs.map((job) => <RecordingJobCard key={job.job_id} job={job} token={accessToken} onChanged={refreshRecordingJobs} />)}
              {pipelineActive.map((m) => <MeetingCard key={m.id} meeting={m} />)}
            </div>
      )}

      {/* Awaiting Review */}
      {tab === "review" && (
        pendingReview.length === 0 && pendingProcessingRequests.length === 0 && !processingRequestsError && !meetingsIncomplete
          ? <EmptyState icon="📭" title="All caught up" sub="No meetings are awaiting your review." />
          : <div className="space-y-7">
              <section aria-labelledby="ai-notes-reviews-heading">
                <h2 id="ai-notes-reviews-heading" className="mb-3 text-base font-semibold text-[#003366]">Existing AI Notes Reviews</h2>
                {pendingReview.length === 0
                  ? !meetingsIncomplete && <p className="text-sm text-[#6b7280]">No AI notes are awaiting review.</p>
                  : <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      {pendingReview.map((m) => <MeetingCard key={m.id} meeting={m} />)}
                    </div>}
              </section>
              <section aria-labelledby="recording-processing-requests-heading">
                <h2 id="recording-processing-requests-heading" className="mb-3 text-base font-semibold text-[#003366]">Recording Processing Requests</h2>
                {processingRequestsError && <p role="alert" className="mb-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">{processingRequestsError}</p>}
                {pendingProcessingRequests.length === 0
                  ? !processingRequestsError && <p className="text-sm text-[#6b7280]">No recording processing requests are awaiting approval.</p>
                  : <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      {pendingProcessingRequests.map((request) => (
                        <article key={request.id} className="rounded-lg border border-[#dde1e8] bg-white p-4 shadow-sm">
                          <h3 className="font-semibold text-[#003366]">{request.subject || "Meeting"}</h3>
                          <p className="mt-2 text-sm text-[#6b7280]">Requested by: {request.requester_name || "Requester"}</p>
                          {request.can_decide && (
                            <div className="mt-4 flex gap-2">
                              {[{ label: "Approve", approved: true }, { label: "Reject", approved: false }].map(({ label, approved }) => (
                                <button key={label} type="button" disabled={processingRequestBusy === request.id}
                                  className="rounded-md bg-[#003366] px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
                                  onClick={() => {
                                    setProcessingRequestBusy(request.id);
                                    void decideRecordingProcessing(request.id, approved, accessToken)
                                      .then(refreshProcessingRequests)
                                      .catch((error: unknown) => setProcessingRequestsError(error instanceof Error ? error.message : "Could not update the request."))
                                      .finally(() => setProcessingRequestBusy(null));
                                  }}>
                                  {label}
                                </button>
                              ))}
                            </div>
                          )}
                        </article>
                      ))}
                    </div>}
              </section>
            </div>
      )}

      {/* Old Meetings */}
      {tab === "old_meetings" && (
        <>
          {historicalError && <p role="alert" className="mb-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">{historicalError}</p>}
          {oldMeetings.length === 0
          ? !meetingsIncomplete && <EmptyState icon="📂" title="No completed meetings yet" sub="Approved and sent meetings will appear here." />
          : <div className="overflow-x-auto rounded-lg">
            <div className="min-w-[760px] bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    {["Meeting", "Date", "Organiser", "Participants", "Status", ""].map((h) => (
                      <th key={h} className="bg-[#003366] text-white text-xs font-semibold px-4 py-2.5 text-left border border-white/10">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {oldMeetings.map((m, i) => (
                    <tr key={m.id} className={`${i % 2 === 1 ? "bg-[#f8fafc]" : ""} hover:bg-blue-50/30 transition-colors`}>
                      <td className="px-4 py-2.5 border border-[#dde1e8] font-medium">
                        <Link href={`/meetings/${m.id}`} className="hover:text-[#003366] hover:underline">
                          {m.title ?? "Untitled Meeting"}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                        {<LocalDateTime value={m.recorded_at ?? m.extracted_json?.meeting_time} />}
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px]">
                        {formatUpn(m.organizer_upn) || "—"}
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px] text-center">
                        {m.calendar_participants.length}
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8]">
                        <StateBadge state={m.state} />
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8]">
                        <div className="flex items-center gap-3 whitespace-nowrap">
                          <Link
                            href={`/meetings/${m.id}`}
                            className="text-[11.5px] font-semibold text-[#003366] hover:text-[#C9A52C] hover:underline"
                          >
                            View notes
                          </Link>
                          {m.organizer_upn?.toLowerCase() === upn.toLowerCase() && (
                            <button
                              type="button"
                              onClick={() => setShareModal({ meetingId: m.id, title: m.title ?? "Untitled Meeting" })}
                              className="inline-flex items-center gap-1 text-[11.5px] text-[#003366] hover:text-[#C9A52C] transition-colors"
                              title="Share transcript"
                            >
                              <Share2 size={13} /> Share
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </div>}
        </>
      )}

      {/* Cancelled */}
      {tab === "cancelled" && (
        cancelled.length === 0
          ? !meetingsIncomplete && <EmptyState icon="🚫" title="No failed or cancelled recordings" sub="Failed and explicitly cancelled recordings appear here." />
          : <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {cancelled.map((m) => <MeetingCard key={m.id} meeting={m} />)}
            </div>
      )}

      {/* Share modal */}
      {shareModal && (
        <ShareModal
          meetingId={shareModal.meetingId}
          meetingTitle={shareModal.title}
          callerUpn={accessToken}
          onClose={() => setShareModal(null)}
        />
      )}
    </main>
  );
}

function RecordingJobCard({ job, token, onChanged }: { job: RecordingJobOut; token: string; onChanged: () => Promise<void> }) {
  return (
    <div className="bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
      <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-4 py-3.5">
        <p className="text-white text-[13.5px] font-semibold leading-snug line-clamp-2">{job.title ?? "Recording queued for import"}</p>
      </div>
      <div className="px-4 py-3.5">
        <StateBadge state={job.processing_status} />
        <p className="mt-2 text-xs leading-5 text-[#6b7280]">{recordingStatusMessage(job)}</p>
        <div className="mt-3 flex items-center justify-between border-t border-[#dde1e8] pt-2.5">
          <JobControls job={job} token={token} onChanged={onChanged} />
          {job.meeting_id && <Link href={`/meetings/${job.meeting_id}`} className="text-[12.5px] font-semibold text-[#003366] hover:underline">View Progress</Link>}
        </div>
      </div>
    </div>
  );
}

/** Card component for a meeting that has been imported into the processing pipeline. */
function MeetingCard({ meeting: m }: { meeting: MeetingOut }) {
  const isProcessing = PIPELINE_STATES.includes(m.state);
  return (
    <Link href={`/meetings/${m.id}`} className="group block bg-white rounded-lg border border-[#dde1e8] shadow-sm hover:border-[#003366] hover:shadow-md transition-all overflow-hidden">
      <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-4 py-3.5">
        <p className="text-white text-[13.5px] font-semibold leading-snug line-clamp-2">
          {m.title ?? "Untitled Meeting"}
        </p>
      </div>
      <div className="px-4 py-3.5">
        <div className="flex flex-col gap-1.5 mb-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span className="flex items-center gap-1 text-[#6b7280] text-[12.5px]">
              <Calendar size={12} className="shrink-0" /> {<LocalDateTime value={m.recorded_at ?? m.extracted_json?.meeting_time} />}
            </span>
            <span className="flex items-center gap-1 text-[#6b7280] text-[12.5px]">
              <Users size={12} className="shrink-0" /> {m.calendar_participants.length} participants
            </span>
          </div>
          {m.organizer_upn && (
            <span className="flex items-center gap-1 text-[#6b7280] text-[12.5px]">
              <Mic size={12} className="shrink-0" /> Organised by: {formatUpn(m.organizer_upn)}
            </span>
          )}
        </div>
        <div className="flex items-center justify-between pt-2.5 border-t border-[#dde1e8]">
          <StateBadge state={m.state} />
          <span className="text-[#003366] text-[12.5px] font-semibold flex items-center gap-0.5 group-hover:gap-1.5 transition-all">
            {isProcessing ? "View Progress" : m.state === "failed" ? "View Error" : "Review"} <ChevronRight size={14} />
          </span>
        </div>
      </div>
    </Link>
  );
}

/** Card component for a calendar event not yet recorded/imported.
 *  Shows a pulsing "Live" badge when the meeting is currently in progress. */
function CalendarCard({ event: ev, inProgress }: { event: CalendarEvent; inProgress?: boolean }) {
  const zone = useUserTimeZone();
  const { dateLabel, timeRange, duration } = zone ? formatEventTime(ev.start, ev.end, zone) : { dateLabel: "—", timeRange: "—", duration: "" };
  return (
    <div className={`bg-white rounded-lg border shadow-sm overflow-hidden hover:shadow-md transition-all ${inProgress ? "border-indigo-300 hover:border-indigo-500" : "border-[#dde1e8] hover:border-[#003366]"}`}>
      <div className={`border-b-[3px] border-[#C9A52C] px-4 py-3.5 flex items-start justify-between gap-2 ${inProgress ? "bg-indigo-700" : "bg-[#003366]"}`}>
        <p className="text-white text-[13.5px] font-semibold leading-snug line-clamp-2 flex-1">
          {ev.subject}
        </p>
        <span className={`shrink-0 text-[10.5px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide ${inProgress ? "bg-green-400 text-green-900 animate-pulse" : "bg-[#C9A52C] text-[#003366]"}`}>
          {inProgress ? "Live" : dateLabel}
        </span>
      </div>
      <div className="px-4 py-3.5">
        <div className="flex flex-col gap-1.5 mb-3">
          <span className="flex items-center gap-1.5 text-[#6b7280] text-[12.5px]">
            <Calendar size={12} className="shrink-0" />
            {dateLabel} · {timeRange}
            {duration && <span className="text-[#9ca3af] ml-1">({duration})</span>}
          </span>
          <span className="flex items-center gap-1.5 text-[#6b7280] text-[12.5px]">
            <Users size={12} className="shrink-0" />
            {ev.attendee_count} participant{ev.attendee_count !== 1 ? "s" : ""}
          </span>
          {ev.organizer_name && (
            <span className="flex items-center gap-1.5 text-[#6b7280] text-[12.5px]">
              <Mic size={12} className="shrink-0" /> Organised by: {ev.organizer_name}
            </span>
          )}
        </div>
        <div className="flex items-center justify-between pt-2.5 border-t border-[#dde1e8]">
          <span className="inline-flex items-center gap-1.5 bg-blue-50 text-blue-700 text-[11.5px] font-semibold px-2.5 py-0.5 rounded-full">
            <Video size={11} /> Teams
          </span>
          <span className="text-[#9ca3af] text-[11.5px]">{inProgress ? "Meeting in progress" : "Recording pending"}</span>
        </div>
      </div>
    </div>
  );
}

/** Full-tab empty state placeholder shown when a tab has no items to display. */
function EmptyState({ icon, title, sub }: { icon: string; title: string; sub: string }) {
  return (
    <div className="text-center py-16 text-[#6b7280]">
      <div className="text-4xl mb-3">{icon}</div>
      <h3 className="text-[15px] font-semibold text-[#1a1a2e] mb-1">{title}</h3>
      <p className="text-[13.5px]">{sub}</p>
    </div>
  );
}

/** Share dialog — organiser can share a transcript with any @taxconsulting.co.za address. */
function ShareModal({
  meetingId,
  meetingTitle,
  callerUpn,
  onClose,
}: {
  meetingId: string;
  meetingTitle: string;
  callerUpn: string;
  onClose: () => void;
}) {
  const [recipient, setRecipient] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  async function handleShare() {
    if (!recipient.endsWith("@taxconsulting.co.za")) {
      setStatus("error");
      setMessage("Only @taxconsulting.co.za addresses are allowed.");
      return;
    }
    setStatus("loading");
    try {
      const res = await shareMeeting(meetingId, recipient, callerUpn);
      setStatus("success");
      setMessage(res.message);
    } catch (e: unknown) {
      setStatus("error");
      setMessage(e instanceof Error ? e.message : "Share failed");
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
        <div className="bg-[#003366] border-b-4 border-[#C9A52C] px-6 py-4">
          <h2 className="text-white font-semibold text-[15px] flex items-center gap-2">
            <Share2 size={16} /> Share Transcript
          </h2>
          <p className="text-white/60 text-[12px] mt-0.5 truncate">{meetingTitle}</p>
        </div>
        <div className="px-6 py-5 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-[12.5px] font-medium text-[#374151]">Recipient email</label>
            <input
              type="email"
              placeholder="colleague@taxconsulting.co.za"
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
              className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
            />
            <p className="text-[11.5px] text-[#9ca3af]">Only @taxconsulting.co.za addresses are accepted.</p>
          </div>
          {status === "error" && (
            <p className="text-[12.5px] text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">{message}</p>
          )}
          {status === "success" && (
            <p className="text-[12.5px] text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2">{message}</p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-[13px] text-[#6b7280] hover:text-[#1a1a2e]">
              {status === "success" ? "Close" : "Cancel"}
            </button>
            {status !== "success" && (
              <button
                type="button"
                onClick={handleShare}
                disabled={!recipient || status === "loading"}
                className="px-4 py-2 text-[13px] font-semibold bg-[#003366] text-white rounded-md hover:bg-[#0a4a8c] disabled:opacity-50"
              >
                {status === "loading" ? "Sharing…" : "Share"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
