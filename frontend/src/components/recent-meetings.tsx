"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import LocalDateTime from "./local-date-time";
import { getRecentMeetings, getProcessingRequests, requestRecordingProcessing, decideRecordingProcessing, processRecentMeeting } from "@/lib/api";
import type { MeetingOut, RecentMeeting, RecordingProcessingRequest } from "@/lib/types";

const RECENT_MEETINGS_CACHE_TTL_MS = 5 * 60 * 1000;
const RECENT_MEETINGS_CACHE_VERSION = 1;

interface RecentMeetingsCacheEntry {
  version: number;
  cachedAt: number;
  events: RecentMeeting[];
}

function cacheKey(identity: string) {
  return `meeting-intel:recent-meetings:v${RECENT_MEETINGS_CACHE_VERSION}:${encodeURIComponent(identity.toLowerCase())}`;
}

function readCache(identity: string): RecentMeetingsCacheEntry | null {
  try {
    const value = sessionStorage.getItem(cacheKey(identity));
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<RecentMeetingsCacheEntry>;
    if (parsed.version !== RECENT_MEETINGS_CACHE_VERSION || typeof parsed.cachedAt !== "number" || !Array.isArray(parsed.events)) {
      sessionStorage.removeItem(cacheKey(identity));
      return null;
    }
    return parsed as RecentMeetingsCacheEntry;
  } catch {
    return null;
  }
}

function writeCache(identity: string, events: RecentMeeting[]) {
  try {
    sessionStorage.setItem(cacheKey(identity), JSON.stringify({
      version: RECENT_MEETINGS_CACHE_VERSION,
      cachedAt: Date.now(),
      events,
    } satisfies RecentMeetingsCacheEntry));
  } catch {
    // Storage can be unavailable; the in-memory state still provides the existing behavior.
  }
}

type TimeFilter = "7" | "30" | "all";
type RecordingFilter = "with" | "without" | "all";
type OrganizerFilter = "all" | "me" | "others";

function normalized(value: string | null | undefined) {
  return (value ?? "").trim().toLowerCase();
}

function historicalDate(meeting: MeetingOut) {
  return meeting.recorded_at ?? meeting.extracted_json?.meeting_time ?? null;
}

function compatibilityKey(title: string | null | undefined, date: string | null | undefined, organizer: string | null | undefined) {
  const instant = date ? Date.parse(date) : NaN;
  return [normalized(title), Number.isNaN(instant) ? normalized(date) : String(instant), normalized(organizer)].join("|");
}

export default function RecentMeetings({ token, cacheIdentity = "current-user", isSubscribed, historical = [], processingRequests, onRefreshProcessingRequests, onRequestHistoricalAccess }: {
  token: string;
  cacheIdentity?: string;
  isSubscribed: boolean;
  historical?: MeetingOut[];
  processingRequests?: RecordingProcessingRequest[];
  onRefreshProcessingRequests?: () => Promise<void>;
  onRequestHistoricalAccess?: (meetingId: string) => Promise<void>;
}) {
  const [events, setEvents] = useState<RecentMeeting[]>([]);
  const [requests, setRequests] = useState<RecordingProcessingRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("7");
  const [recordingFilter, setRecordingFilter] = useState<RecordingFilter>("with");
  const [organizerFilter, setOrganizerFilter] = useState<OrganizerFilter>("all");
  const controlledRequests = processingRequests !== undefined;
  const processingRequestsRef = useRef(processingRequests);
  processingRequestsRef.current = processingRequests;
  const load = useCallback(() => Promise.allSettled([
      isSubscribed ? getRecentMeetings(token) : Promise.resolve([]),
      controlledRequests ? Promise.resolve(processingRequestsRef.current ?? []) : getProcessingRequests(token),
    ]), [token, isSubscribed, controlledRequests]);
  const applyResults = useCallback((results: Awaited<ReturnType<typeof load>>, options?: { silent?: boolean }) => {
    const errors: string[] = [];
    if (results[0].status === "fulfilled") {
      setEvents(results[0].value);
      if (isSubscribed) writeCache(cacheIdentity, results[0].value);
    }
    else if (!options?.silent) errors.push("Recent Meetings unavailable. Please refresh to retry.");
    if (results[1].status === "fulfilled") setRequests(results[1].value);
    else if (!options?.silent) errors.push("Processing requests unavailable.");
    setError(errors.join(" "));
    setLoading(false);
  }, [cacheIdentity, isSubscribed]);

  useEffect(() => {
    let active = true;
    const cached = isSubscribed ? readCache(cacheIdentity) : null;
    if (cached) {
      setEvents(cached.events);
      setLoading(false);
      setError("");
    }

    // A cached result is rendered immediately. Revalidate it without replacing
    // the page with a loading state, especially once its TTL has elapsed.
    const isStale = cached ? Date.now() - cached.cachedAt >= RECENT_MEETINGS_CACHE_TTL_MS : false;
    void load().then((results) => {
      if (active) applyResults(results, { silent: Boolean(cached) || isStale });
    });
    return () => { active = false; };
  }, [load, applyResults, cacheIdentity, isSubscribed]);

  useEffect(() => {
    if (processingRequests !== undefined) setRequests(processingRequests);
  }, [processingRequests]);

  async function refresh() {
    setRefreshing(true);
    setError("");
    try {
      applyResults(await load());
      await onRefreshProcessingRequests?.();
    }
    finally { setRefreshing(false); }
  }

  async function act(operation: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try { await operation(); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Action failed; refresh before retrying."); }
    finally { setBusy(false); }
  }

  const recentMeetingIds = new Set(events.flatMap((event) => event.meeting_id ? [event.meeting_id] : []));
  const recentCompatibilityKeys = new Set(events
    .filter((event) => !event.meeting_id)
    .map((event) => compatibilityKey(event.subject, event.start, event.organizer_email)));
  const historicalOnly = historical.filter((meeting) =>
    !recentMeetingIds.has(meeting.id)
    && !recentCompatibilityKeys.has(compatibilityKey(meeting.title, historicalDate(meeting), meeting.organizer_upn)),
  );
  const rows = [
    ...events.map((event) => ({ kind: "recent" as const, id: event.event_id, date: event.start, organizer: event.organizer_email, hasRecording: event.action !== "no_recording", event })),
    ...historicalOnly.map((meeting) => ({ kind: "historical" as const, id: meeting.id, date: historicalDate(meeting), organizer: meeting.organizer_upn, hasRecording: true, meeting })),
  ].filter((row) => {
    const timestamp = row.date ? Date.parse(row.date) : NaN;
    const cutoffDays = timeFilter === "7" ? 7 : timeFilter === "30" ? 30 : null;
    if (cutoffDays !== null && (Number.isNaN(timestamp) || timestamp < Date.now() - cutoffDays * 24 * 60 * 60 * 1000)) return false;
    if (recordingFilter === "with" && !row.hasRecording) return false;
    if (recordingFilter === "without" && row.hasRecording) return false;
    const organizedByMe = normalized(row.organizer) === normalized(cacheIdentity);
    return organizerFilter === "all" || (organizerFilter === "me" ? organizedByMe : !organizedByMe);
  }).sort((a, b) => (b.date ? Date.parse(b.date) : 0) - (a.date ? Date.parse(a.date) : 0));

  const buttonClass = "rounded-md bg-[#003366] px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50";
  return (
    <section aria-label="Meetings">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-sm text-[#6b7280]">Meetings you participated in, including available historical meetings.</p>
        <button type="button" className={buttonClass} disabled={busy || loading || refreshing} onClick={() => void refresh()}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <p role="alert" className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
      {loading && <p role="status">Loading recent meetings and processing requests…</p>}
      {refreshing && <p role="status" className="mb-3 text-sm text-[#6b7280]">Refreshing recent meetings and processing requests…</p>}
      {!isSubscribed && <p className="mb-4 text-sm">Subscribe to discover recent Calendar meetings and recordings.</p>}
      <div className="mb-5 flex flex-wrap gap-3">
        <label className="text-sm font-medium text-[#374151]">Time
          <select aria-label="Time" className="ml-2 rounded-md border border-[#dde1e8] bg-white px-2 py-1.5" value={timeFilter} onChange={(e) => setTimeFilter(e.target.value as TimeFilter)}>
            <option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="all">All available history</option>
          </select>
        </label>
        <label className="text-sm font-medium text-[#374151]">Recording
          <select aria-label="Recording" className="ml-2 rounded-md border border-[#dde1e8] bg-white px-2 py-1.5" value={recordingFilter} onChange={(e) => setRecordingFilter(e.target.value as RecordingFilter)}>
            <option value="with">With Recording</option><option value="without">No Recording</option><option value="all">All</option>
          </select>
        </label>
        <label className="text-sm font-medium text-[#374151]">Organizer
          <select aria-label="Organizer" className="ml-2 rounded-md border border-[#dde1e8] bg-white px-2 py-1.5" value={organizerFilter} onChange={(e) => setOrganizerFilter(e.target.value as OrganizerFilter)}>
            <option value="all">All</option><option value="me">Organized by me</option><option value="others">Organized by others</option>
          </select>
        </label>
      </div>
      {!loading && !error && isSubscribed && rows.length === 0 && <p>No meetings match these filters.</p>}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((row) => row.kind === "recent" ? (() => { const event = row.event; return (
          <article key={`recent:${event.event_id}`} className="rounded-lg border border-[#dde1e8] bg-white p-4">
            <h3 className="font-semibold text-[#003366]">{event.subject}</h3>
            <p className="my-2 text-sm text-[#6b7280]"><LocalDateTime value={event.start} /></p>
            <p className="mb-3 text-xs text-[#6b7280]">Organised by {event.organizer_name || event.organizer_email}</p>
            <p className="mb-3 text-xs font-semibold text-[#6b7280]">{event.action === "no_recording" ? "No Recording" : "Recording Available"}</p>
            {event.action === "view" && event.meeting_id && <Link className="font-semibold text-[#003366] underline" href={`/meetings/${event.meeting_id}`}>View</Link>}
            {event.action === "process" && <button type="button" disabled={busy || loading} className={buttonClass} onClick={() => void act(() => processRecentMeeting(event.event_id, token))}>Process</button>}
            {event.action === "request_processing" && <button type="button" disabled={busy || loading} className={buttonClass} onClick={() => void act(() => requestRecordingProcessing(event.event_id, token))}>Request Processing</button>}
            {event.action === "request_pending" && <span className="text-sm text-amber-800">Request Pending</span>}
            {event.action === "processing" && <span className="text-sm text-blue-800">Processing: {event.processing_status === "pending" ? "Queued" : event.processing_status || "Unavailable"}</span>}
            {event.action === "unavailable" && <span className="text-sm text-amber-800">Unavailable</span>}
            {event.reason && <p className="mt-2 text-xs text-[#6b7280]">{event.reason}</p>}
          </article>
        ); })() : (() => { const meeting = row.meeting; return (
          <article key={`historical:${meeting.id}`} className="rounded-lg border border-[#dde1e8] bg-white p-4">
            <h3 className="font-semibold text-[#003366]">{meeting.title ?? "Untitled Meeting"}</h3>
            <p className="my-2 text-sm text-[#6b7280]"><LocalDateTime value={historicalDate(meeting)} /></p>
            <p className="mb-3 text-xs text-[#6b7280]">Organised by {meeting.organizer_upn || "Unknown"}</p>
            <p className="mb-3 text-xs font-semibold text-[#6b7280]">Recording Available</p>
            {onRequestHistoricalAccess && <button type="button" disabled={busy} className={buttonClass} onClick={() => void act(() => onRequestHistoricalAccess(meeting.id))}>Request Access</button>}
          </article>
        ); })())}
      </div>
      <h3 className="mb-3 mt-8 font-semibold text-[#003366]">Recording processing requests</h3>
      <p className="mb-3 text-sm text-[#6b7280]">The recording owner approves processing only. Editing and final notes approval stay separate.</p>
      {!loading && !requests.length && <p className="text-sm">No processing requests.</p>}
      <ul className="space-y-3">
        {requests.map((request) => (
          <li key={request.id} className="rounded-lg border border-[#dde1e8] bg-white p-4">
            <p className="font-medium">{request.subject || "Meeting"}</p>
            <p className="my-1 text-sm"><LocalDateTime value={request.start} /> · {request.requester_name || "Requester"}</p>
            <p className="text-sm capitalize">{request.status}</p>
            {request.can_decide && <div className="mt-3 flex gap-2">
              <button type="button" className={buttonClass} disabled={busy || loading || !isSubscribed} onClick={() => void act(() => decideRecordingProcessing(request.id, true, token))}>Approve</button>
              <button type="button" className={buttonClass} disabled={busy || loading} onClick={() => void act(() => decideRecordingProcessing(request.id, false, token))}>Deny</button>
            </div>}
          </li>
        ))}
      </ul>
    </section>
  );
}
