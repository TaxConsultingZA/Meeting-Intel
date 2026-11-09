"use client";

import Link from "next/link";
import LoadingSpinner from "./loading-spinner";
import { useCallback, useEffect, useRef, useState } from "react";
import LocalDateTime from "./local-date-time";
import { getRecentMeetings, getProcessingRequests, requestRecordingProcessing, decideRecordingProcessing, processRecentMeeting } from "@/lib/api";
import { parseInstant } from "@/lib/time";
import type { MeetingOut, RecentMeeting, RecordingProcessingRequest } from "@/lib/types";

const RECENT_MEETINGS_CACHE_TTL_MS = 5 * 60 * 1000;
const RECENT_MEETINGS_CACHE_VERSION = 4;

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
type MonthChoice = { month: string; year: string };
const johannesburg = "Africa/Johannesburg";
const monthNames = Array.from({ length: 12 }, (_, month) =>
  new Intl.DateTimeFormat("en-ZA", { month: "long", timeZone: "UTC" }).format(new Date(Date.UTC(2024, month, 1))));
const monthDayLabel = new Intl.DateTimeFormat("en-ZA", { dateStyle: "long", timeZone: johannesburg });

function currentMonth(): MonthChoice {
  const parts = new Intl.DateTimeFormat("en", { month: "numeric", year: "numeric", timeZone: johannesburg }).formatToParts();
  return { month: parts.find(part => part.type === "month")!.value, year: parts.find(part => part.type === "year")!.value };
}

function monthRange({ year, month }: MonthChoice) {
  // Johannesburg has used UTC+02:00 year-round since 1944.
  if (!/^\d{4}$/.test(year) || Number(year) < 1945 || Number(year) > 9998) return null;
  const midnight = (monthIndex: number) => new Date(Date.UTC(Number(year), monthIndex, 1, -2));
  return {
    start_from: midnight(Number(month) - 1).toISOString(),
    start_before: midnight(Number(month)).toISOString(),
  };
}

function normalized(value: string | null | undefined) {
  return (value ?? "").trim().toLowerCase();
}

function historicalDate(meeting: MeetingOut) {
  return meeting.recorded_at ?? meeting.extracted_json?.meeting_time ?? null;
}

export default function RecentMeetings({ token, cacheIdentity = "current-user", isSubscribed, accessibleMeetings = [], historical = [], processingRequests, onRefreshProcessingRequests, onRequestHistoricalAccess, onRequestMeetingEditAccess, refreshKey = 0 }: {
  token: string;
  cacheIdentity?: string;
  isSubscribed: boolean;
  refreshKey?: number;
  accessibleMeetings?: MeetingOut[];
  historical?: MeetingOut[];
  processingRequests?: RecordingProcessingRequest[];
  onRefreshProcessingRequests?: () => Promise<void>;
  onRequestHistoricalAccess?: (meetingId: string, accessType: "view" | "edit") => Promise<void>;
  onRequestMeetingEditAccess?: (meetingId: string) => Promise<void>;
}) {
  const [events, setEvents] = useState<RecentMeeting[]>([]);
  const [requests, setRequests] = useState<RecordingProcessingRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("7");
  const [monthOpen, setMonthOpen] = useState(false);
  const [monthChoice, setMonthChoice] = useState(currentMonth);
  const [appliedMonth, setAppliedMonth] = useState<{
    choice: MonthChoice;
    range: NonNullable<ReturnType<typeof monthRange>>;
    events: RecentMeeting[];
  } | null>(null);
  const [monthError, setMonthError] = useState("");
  const [recordingFilter, setRecordingFilter] = useState<RecordingFilter>("with");
  const [organizerFilter, setOrganizerFilter] = useState<OrganizerFilter>("all");
  const [search, setSearch] = useState("");
  const [choosingAccessFor, setChoosingAccessFor] = useState<string | null>(null);
  const controlledRequests = processingRequests !== undefined;
  const processingRequestsRef = useRef(processingRequests);
  useEffect(() => {
    processingRequestsRef.current = processingRequests;
  }, [processingRequests]);
  const load = useCallback(async (active: () => boolean = () => true, silent = false) => {
    const errors: string[] = [];
    const report = (message: string) => {
      if (!active() || silent) return;
      errors.push(message);
      setError(errors.join(" "));
    };
    // Publish each read as it settles; the other read may still be pending.
    await Promise.allSettled([
      (isSubscribed ? getRecentMeetings(token, true) : Promise.resolve([])).then((rows) => {
        if (!active()) return;
        setEvents(rows);
        if (isSubscribed) writeCache(cacheIdentity, rows);
      }).catch(() => report("Recent Meetings unavailable. Please refresh to retry."))
        .finally(() => { if (active()) setLoading(false); }),
      (controlledRequests ? Promise.resolve(processingRequestsRef.current ?? []) : getProcessingRequests(token, null))
        .then((rows) => { if (active()) setRequests(rows); })
        .catch(() => report("Processing requests unavailable.")),
    ]);
    if (active()) setError(errors.join(" "));
  }, [token, isSubscribed, controlledRequests, cacheIdentity]);

  useEffect(() => {
    let active = true;
    const cached = isSubscribed ? readCache(cacheIdentity) : null;
    if (cached) {
      // Restore browser storage before background revalidation, preserving instant remounts.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setEvents(cached.events);
      setLoading(false);
      setError("");
    }

    // A cached result is rendered immediately. Revalidate it without replacing
    // the page with a loading state, especially once its TTL has elapsed.
    const isStale = cached ? Date.now() - cached.cachedAt >= RECENT_MEETINGS_CACHE_TTL_MS : false;
    void load(() => active, Boolean(cached) || isStale);
    return () => { active = false; };
  }, [load, cacheIdentity, isSubscribed, refreshKey]);

  const displayedRequests = processingRequests ?? requests;

  async function refresh(month = appliedMonth?.choice) {
    const range = month && monthRange(month);
    if (month && !range) {
      setMonthError("Enter a four-digit year from 1945 to 9998.");
      return;
    }
    setRefreshing(true);
    setError("");
    setMonthError("");
    try {
      if (month && range) {
        const rows = isSubscribed ? await getRecentMeetings(token, true, range) : [];
        setAppliedMonth({ choice: month, range, events: rows });
      } else {
        await load();
        await onRefreshProcessingRequests?.();
      }
    }
    catch { setError("Meetings could not be refreshed. Please try again."); }
    finally { setRefreshing(false); }
  }

  async function act(operation: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try { await operation(); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Action failed; refresh before retrying."); }
    finally { setBusy(false); }
  }

  // These records already passed /reviews/all access checks. Calendar cache is
  // only a discovery source and must not determine their visibility.
  const savedDate = (meeting: MeetingOut) =>
    appliedMonth && meeting.card_date ? meeting.card_date.value : historicalDate(meeting);
  const monthStart = appliedMonth ? new Date(appliedMonth.range.start_from) : null;
  const monthEnd = appliedMonth ? new Date(appliedMonth.range.start_before) : null;
  const inMonth = (value: string | null) => {
    if (!monthStart || !monthEnd) return true;
    const instant = parseInstant(value);
    return instant !== null && instant >= monthStart && instant < monthEnd;
  };
  const accessible = [...new Map(accessibleMeetings.filter(meeting => inMonth(savedDate(meeting))).map((meeting) => [meeting.id, meeting])).values()];
  const accessibleIds = new Set(accessible.map((meeting) => meeting.id));
  const meetingIds = new Set(accessibleIds);
  const eventIds = new Set<string>();
  const recentOnly = (appliedMonth?.events ?? events).filter((event) => {
    if (!inMonth(event.start) || eventIds.has(event.event_id) || (event.meeting_id && meetingIds.has(event.meeting_id))) return false;
    eventIds.add(event.event_id);
    if (event.meeting_id) meetingIds.add(event.meeting_id);
    return true;
  });
  const historicalOnly = historical.filter((meeting) => {
    if (!inMonth(savedDate(meeting)) || meetingIds.has(meeting.id)) return false;
    meetingIds.add(meeting.id);
    return true;
  });
  const rows = [
    ...accessible.map((meeting) => ({ kind: "accessible" as const, id: meeting.id, date: savedDate(meeting), organizer: meeting.organizer_upn, hasRecording: true, meeting })),
    ...recentOnly.map((event) => ({ kind: "recent" as const, id: event.event_id, date: event.start, organizer: event.organizer_email, hasRecording: event.action !== "no_recording", event })),
    ...historicalOnly.map((meeting) => ({ kind: "historical" as const, id: meeting.id, date: savedDate(meeting), organizer: meeting.organizer_upn, hasRecording: true, meeting })),
  ].filter((row) => {
    const timestamp = parseInstant(row.date)?.getTime() ?? NaN;
    const cutoffDays = appliedMonth ? null : timeFilter === "7" ? 7 : timeFilter === "30" ? 30 : null;
    // Preserve the existing wall-clock cutoff whenever the list renders.
    // eslint-disable-next-line react-hooks/purity
    if (cutoffDays !== null && (Number.isNaN(timestamp) || timestamp < Date.now() - cutoffDays * 24 * 60 * 60 * 1000)) return false;
    if (recordingFilter === "with" && !row.hasRecording) return false;
    if (recordingFilter === "without" && row.hasRecording) return false;
    const organizedByMe = normalized(row.organizer) === normalized(cacheIdentity);
    if (organizerFilter !== "all" && (organizerFilter === "me" ? !organizedByMe : organizedByMe)) return false;
    const query = normalized(search);
    if (!query) return true;
    const searchable = row.kind === "recent"
      ? [row.event.subject, ...row.event.attendees]
      : [row.meeting.title, row.meeting.summary, ...row.meeting.calendar_participants.map((participant) => participant.name)];
    return searchable.some((value) => normalized(value).includes(query));
  }).sort((a, b) => (b.date ? Date.parse(b.date) : 0) - (a.date ? Date.parse(a.date) : 0));

  const buttonClass = "rounded-md bg-[#003366] px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50";
  return (
    <section aria-label="Meetings">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-sm text-[#6b7280]">Meetings you participated in, including available historical meetings.</p>
      </div>
      {error && <p role="alert" className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
      {loading && rows.length === 0 && <div role="status" aria-label="Recent meetings loading" className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((card) => <div key={card} aria-hidden="true" className="min-h-40 space-y-4 rounded-lg border border-[#dde1e8] bg-white p-4 motion-safe:animate-pulse">
          <div className="h-4 w-3/4 rounded bg-[#e5eaf2]" />
          <div className="h-3 w-2/3 rounded bg-[#eef1f6]" />
          <div className="h-3 w-1/2 rounded bg-[#eef1f6]" />
          <div className="h-8 w-20 rounded bg-[#e5eaf2]" />
        </div>)}
      </div>}
      {refreshing && <LoadingSpinner label="Recent meetings refreshing" />}
      {!isSubscribed && <p className="mb-4 text-sm">Subscribe to discover recent Calendar meetings and recordings.</p>}
      <div className="mb-5 grid grid-cols-1 items-end gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(220px,2fr)_repeat(3,minmax(135px,1fr))_auto]">
        <div className="flex min-w-0 flex-col gap-1 text-sm font-medium text-[#374151]">Search meetings
          <div className="flex min-w-0 gap-2">
            <input aria-label="Search meetings" type="search" className="min-w-0 flex-1 rounded-md border border-[#dde1e8] bg-white px-3 py-2 font-normal" placeholder="Title, summary, or participant" value={search} onChange={(event) => setSearch(event.target.value)} />
            {search && <button type="button" className="shrink-0 rounded-md border border-[#dde1e8] bg-white px-3 py-2 text-sm" onClick={() => setSearch("")}>Clear search</button>}
          </div>
        </div>
        <label className="flex min-w-0 flex-col gap-1 text-sm font-medium text-[#374151]">Time
          <select aria-label="Time" className="w-full rounded-md border border-[#dde1e8] bg-white px-2 py-2" value={monthOpen ? "month" : timeFilter} disabled={refreshing} onChange={(e) => {
            setMonthError("");
            if (e.target.value === "month") {
              setMonthOpen(true);
            } else {
              setMonthOpen(false);
              setMonthChoice(currentMonth());
              setAppliedMonth(null);
              setTimeFilter(e.target.value as TimeFilter);
            }
          }}>
            <option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="all">All available history</option>
            <option value="month">Choose month</option>
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-sm font-medium text-[#374151]">Recording
          <select aria-label="Recording" className="w-full rounded-md border border-[#dde1e8] bg-white px-2 py-2" value={recordingFilter} onChange={(e) => setRecordingFilter(e.target.value as RecordingFilter)}>
            <option value="with">With Recording</option><option value="without">No Recording</option><option value="all">All</option>
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-sm font-medium text-[#374151]">Organizer
          <select aria-label="Organizer" className="w-full rounded-md border border-[#dde1e8] bg-white px-2 py-2" value={organizerFilter} onChange={(e) => setOrganizerFilter(e.target.value as OrganizerFilter)}>
            <option value="all">All</option><option value="me">Organized by me</option><option value="others">Organized by others</option>
          </select>
        </label>
        {!monthOpen && <button type="button" className={`${buttonClass} min-h-10`} disabled={busy || loading || refreshing} onClick={() => void refresh()}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>}
        {monthOpen && <fieldset disabled={refreshing} className="col-span-full flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">Month
            <select className="rounded-md border border-[#dde1e8] bg-white px-2 py-2" value={monthChoice.month}
              onChange={e => setMonthChoice({ ...monthChoice, month: e.target.value })}>
              {monthNames.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">Year
            <input className="w-28 rounded-md border border-[#dde1e8] bg-white px-2 py-2" inputMode="numeric" maxLength={4}
              value={monthChoice.year} aria-invalid={Boolean(monthError)} onChange={e => {
                setMonthError("");
                setMonthChoice({ ...monthChoice, year: e.target.value });
              }} />
          </label>
          <button type="button" className={`${buttonClass} min-h-10`} disabled={busy || loading} onClick={() => void refresh(monthChoice)}>
            {refreshing ? "Refreshing…" : "Apply month"}
          </button>
          {monthError && <p role="alert">{monthError}</p>}
        </fieldset>}
      </div>
      {monthOpen && <p role="status" className="mb-4 text-sm">
        {appliedMonth ? `Applied dates: ${monthDayLabel.format(new Date(appliedMonth.range.start_from))} – ${monthDayLabel.format(new Date(Date.parse(appliedMonth.range.start_before) - 1))} · Johannesburg time` :
          `Applied time: ${timeFilter === "7" ? "Last 7 days" : timeFilter === "30" ? "Last 30 days" : "All available history"}`}
      </p>}
      {!loading && !error && (isSubscribed || appliedMonth) && rows.length === 0 && <p>{search.trim() ? "No meetings match this search and the selected filters." : "No meetings match these filters."}</p>}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((row) => row.kind === "recent" ? (() => { const event = row.event; return (
          <article key={`recent:${event.event_id}`} className="rounded-lg border border-[#dde1e8] bg-white p-4">
            <h3 className="font-semibold text-[#003366]">{event.subject}</h3>
            <p className="my-2 text-sm text-[#6b7280]"><LocalDateTime value={event.start} /></p>
            <p className="mb-3 text-xs text-[#6b7280]">Organised by {event.organizer_name || event.organizer_email}</p>
            <p className="mb-3 text-xs font-semibold text-[#6b7280]">{event.action === "no_recording" ? "No Recording" : "Recording Available"}</p>
            {event.action === "view" && event.meeting_id && <Link className="font-semibold text-[#003366] underline" href={`/meetings/${event.meeting_id}`}>View</Link>}
            {event.can_request_view_access && event.meeting_id && onRequestHistoricalAccess && <button type="button" disabled={busy || loading} className={buttonClass} onClick={() => void act(() => onRequestHistoricalAccess(event.meeting_id!, "view"))}>Request View</button>}
            {event.can_request_edit_access && event.meeting_id && (event.action === "view" ? onRequestMeetingEditAccess : onRequestHistoricalAccess) && <button type="button" disabled={busy || loading} className={`${buttonClass} ml-2`} onClick={() => void act(() => event.action === "view" ? onRequestMeetingEditAccess!(event.meeting_id!) : onRequestHistoricalAccess!(event.meeting_id!, "edit"))}>Request Edit</button>}
            {event.pending_access_type && <span className="ml-2 text-sm text-amber-800">{event.pending_access_type === "view" ? "View Pending" : "Edit Pending"}</span>}
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
            <p className="my-2 text-sm text-[#6b7280]"><LocalDateTime value={row.date} /></p>
            <p className="mb-3 text-xs text-[#6b7280]">Organised by {meeting.organizer_upn || "Unknown"}</p>
            <p className="mb-3 text-xs font-semibold text-[#6b7280]">Recording Available</p>
            {row.kind === "accessible" ? (
              <>
                <Link className="font-semibold text-[#003366] underline" href={`/meetings/${meeting.id}`}>View</Link>
                {meeting.can_request_edit_access && onRequestMeetingEditAccess && <button type="button" disabled={busy || loading} className={`${buttonClass} ml-2`} onClick={() => void act(() => onRequestMeetingEditAccess(meeting.id))}>Request Edit</button>}
                {meeting.edit_access_status === "pending" && <span className="ml-2 text-sm text-amber-800">Edit Pending</span>}
              </>
            ) : meeting.edit_access_status === "pending" ? (
              <span className="text-sm text-amber-800">
                {meeting.access_request_type === "edit" ? "View and edit" : "View"} request pending
              </span>
            ) : onRequestHistoricalAccess && choosingAccessFor === meeting.id ? (
              <div className="flex flex-wrap gap-2" role="group" aria-label="Choose access type">
                <button type="button" disabled={busy} className={buttonClass} onClick={() => void act(async () => { await onRequestHistoricalAccess(meeting.id, "view"); setChoosingAccessFor(null); })}>View only</button>
                <button type="button" disabled={busy} className={buttonClass} onClick={() => void act(async () => { await onRequestHistoricalAccess(meeting.id, "edit"); setChoosingAccessFor(null); })}>View and edit</button>
                <button type="button" disabled={busy} className="text-sm text-[#6b7280]" onClick={() => setChoosingAccessFor(null)}>Cancel</button>
              </div>
            ) : onRequestHistoricalAccess && (
              <button type="button" disabled={busy} className={buttonClass} onClick={() => setChoosingAccessFor(meeting.id)}>Request Access</button>
            )}
          </article>
        ); })())}
      </div>
      <h3 className="mb-3 mt-8 font-semibold text-[#003366]">Recording processing requests</h3>
      <p className="mb-3 text-sm text-[#6b7280]">The recording owner approves processing only. Editing and final notes approval stay separate.</p>
      {!loading && !displayedRequests.length && <p className="text-sm">No processing requests.</p>}
      <ul className="space-y-3">
        {displayedRequests.map((request) => (
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
