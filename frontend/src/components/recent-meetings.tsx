"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import LocalDateTime from "./local-date-time";
import { getRecentMeetings, getProcessingRequests, requestRecordingProcessing, decideRecordingProcessing, processRecentMeeting } from "@/lib/api";
import type { RecentMeeting, RecordingProcessingRequest } from "@/lib/types";

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

export default function RecentMeetings({ token, cacheIdentity = "current-user", isSubscribed, processingRequests, onRefreshProcessingRequests }: {
  token: string;
  cacheIdentity?: string;
  isSubscribed: boolean;
  processingRequests?: RecordingProcessingRequest[];
  onRefreshProcessingRequests?: () => Promise<void>;
}) {
  const [events, setEvents] = useState<RecentMeeting[]>([]);
  const [requests, setRequests] = useState<RecordingProcessingRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
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

  const buttonClass = "rounded-md bg-[#003366] px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50";
  return (
    <section aria-label="Recent Meetings">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-sm text-[#6b7280]">Calendar meetings you participated in that ended in the past 30 days.</p>
        <button type="button" className={buttonClass} disabled={busy || loading || refreshing} onClick={() => void refresh()}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <p role="alert" className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
      {loading && <p role="status">Loading recent meetings and processing requests…</p>}
      {refreshing && <p role="status" className="mb-3 text-sm text-[#6b7280]">Refreshing recent meetings and processing requests…</p>}
      {!isSubscribed && <p className="mb-4 text-sm">Subscribe to discover recent Calendar meetings and recordings.</p>}
      {!loading && !error && isSubscribed && events.length === 0 && <p>No recently ended meetings.</p>}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {events.map((event) => (
          <article key={event.event_id} className="rounded-lg border border-[#dde1e8] bg-white p-4">
            <h3 className="font-semibold text-[#003366]">{event.subject}</h3>
            <p className="my-2 text-sm text-[#6b7280]"><LocalDateTime value={event.start} /></p>
            <p className="mb-3 text-xs text-[#6b7280]">Organised by {event.organizer_name || event.organizer_email}</p>
            {event.action === "view" && event.meeting_id && <Link className="font-semibold text-[#003366] underline" href={`/meetings/${event.meeting_id}`}>View</Link>}
            {event.action === "process" && <button type="button" disabled={busy || loading} className={buttonClass} onClick={() => void act(() => processRecentMeeting(event.event_id, token))}>Process</button>}
            {event.action === "request_processing" && <button type="button" disabled={busy || loading} className={buttonClass} onClick={() => void act(() => requestRecordingProcessing(event.event_id, token))}>Request Processing</button>}
            {event.action === "request_pending" && <span className="text-sm text-amber-800">Request Pending</span>}
            {event.action === "processing" && <span className="text-sm text-blue-800">Processing: {event.processing_status === "pending" ? "Queued" : event.processing_status || "Unavailable"}</span>}
            {event.action === "no_recording" && <span className="text-sm text-[#6b7280]">No recording found</span>}
            {event.action === "unavailable" && <span className="text-sm text-amber-800">Unavailable</span>}
            {event.reason && <p className="mt-2 text-xs text-[#6b7280]">{event.reason}</p>}
          </article>
        ))}
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
