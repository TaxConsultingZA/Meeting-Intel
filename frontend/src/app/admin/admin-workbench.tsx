"use client";
import { useEffect, useRef, useState } from "react";
import { getAdminMeetings, getRecordingJobs, getAuditEvents, getMeeting } from "@/lib/api";
import type { AdminMeetingOut, RecordingJobOut, AuditEvent, AuditFilters, MeetingOut } from "@/lib/types";
import CalendarDateField, { calendarDateError } from "@/components/calendar-date-field";
import { parseInstant } from "@/lib/time";
import MeetingDetailClient from "../meetings/[id]/meeting-detail-client";
import AdminModal from "./admin-modal";
import { eventTitle, outcomeDescription } from "./audit-logs/audit-display";
import AuditEventDialog from "./audit-logs/audit-event-dialog";
const date = (value: string | null) => {
  const instant = parseInstant(value);
  return instant ? instant.toLocaleString("en-ZA", { timeZone: "Africa/Johannesburg" }) : "Date not available";
};
const dayMs = 86400000;
function bounds({from, to}: {from: string; to: string}) {
  return {
    start: from ? new Date(`${from}T00:00:00+02:00`) : undefined,
    end: to ? new Date(new Date(`${to}T00:00:00+02:00`).getTime() + dayMs) : undefined,
  };
}

const pageSize = 200;

async function collectPages<T>(read: (offset: number) => Promise<T[]>, idOf: (row: T) => string) {
  const rows = new Map<string, T>();
  for (let offset = 0; ; offset += pageSize) {
    const batch = await read(offset);
    const previousSize = rows.size;
    for (const row of batch) rows.set(idOf(row), row);
    if (batch.length < pageSize) return [...rows.values()];
    if (rows.size === previousSize) throw new Error("The records API did not advance to the next page.");
  }
}

const recordDate = (record: AdminMeetingOut) => record.card_date ? record.card_date.value : record.recorded_at;
const input = "w-full min-w-0 rounded border p-2 text-sm";
function readable(value: string) {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function AdminStatus({ value }: { value: string }) {
  return <span className="admin-status">{readable(value)}</span>;
}

export default function AdminWorkbench({ accessToken, callerUpn }: { accessToken: string; callerUpn: string }) {
  const auditFiltersRef = useRef<AuditFilters>({});
  const detailFiltersRef = useRef<AuditFilters>({});
  const [detailEvents, setDetailEvents] = useState<AuditEvent[]>([]);
  const [detailCursor, setDetailCursor] = useState<string | undefined>();
  const [detailBusy, setDetailBusy] = useState(false);
  const [detailActivityError, setDetailActivityError] = useState("");
  const [detailWindow, setDetailWindow] = useState("");
  const activityRequest = useRef(0);
  const contentRequest = useRef(0);
  const recordRequest = useRef(0);
  const detailBody = useRef<HTMLDivElement>(null);
  const [detailOpener, setDetailOpener] = useState<HTMLButtonElement | null>(null);
  async function loadDetailActivity(next?: string) {
    const request = ++activityRequest.current;
    setDetailBusy(true); setDetailActivityError("");
    try {
      const page = await getAuditEvents(accessToken, detailFiltersRef.current, next);
      if (request !== activityRequest.current) return;
      setDetailEvents(old => next ? [...old, ...page.items] : page.items);
      setDetailCursor(page.next_cursor || undefined);
      setDetailWindow(`${date(page.window_start)} – ${date(page.window_end)}`);
    } catch { if (request === activityRequest.current) setDetailActivityError("Activity could not be loaded. Retry this query."); }
    finally { if (request === activityRequest.current) setDetailBusy(false); }
  }
  const [meetings, setMeetings] = useState<AdminMeetingOut[]>([]);
  const [jobs, setJobs] = useState<RecordingJobOut[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | undefined>();
  const [query, setQuery] = useState(""); const [actor, setActor] = useState("");
  const [appliedActor, setAppliedActor] = useState("");
  const [status, setStatus] = useState(""); const [from, setFrom] = useState(""); const [to, setTo] = useState("");
  const [dateSearchAttempted, setDateSearchAttempted] = useState(false);
  const fromError = calendarDateError(from);
  const toError = calendarDateError(to) || (from && to && !fromError && from > to ? "To must be on or after From." : undefined);
  const [appliedDates, setAppliedDates] = useState({from: "", to: ""});
  const [activityError, setActivityError] = useState(false);
  const {start, end} = bounds(appliedDates);
  const [busy, setBusy] = useState(true); const [error, setError] = useState("");
  const [selected, setSelected] = useState<AdminMeetingOut | null>(null);
  const [content, setContent] = useState<MeetingOut | null>(null);
  const [detailError, setDetailError] = useState("");
  const [windowLabel, setWindowLabel] = useState("");
  const [event, setEvent] = useState<AuditEvent | null>(null);
  async function load(next?: string, actorValue = appliedActor, dates = appliedDates) {
    const request = ++recordRequest.current;
    const current = () => request === recordRequest.current;
    setBusy(true); setError(""); setActivityError(false);
    if (!next) { setEvents([]); setCursor(undefined); setWindowLabel(""); }
    try {
      const filters: AuditFilters = actorValue.trim() ? (actorValue.includes("@") ? { actor_upn: actorValue.trim() } : { actor_id: actorValue.trim() }) : {};
      if (!next) {
        const {start, end} = bounds(dates);
        if (start) {
          filters.from = start.toISOString();
          const upper = end?.getTime() ?? Math.max(Date.now(), start.getTime() + dayMs);
          filters.to = new Date(Math.min(upper, start.getTime() + 90 * dayMs)).toISOString();
        } else if (end) filters.to = end.toISOString();
        auditFiltersRef.current = filters;
      }
      try {
        const page = await getAuditEvents(accessToken, auditFiltersRef.current, next);
        if (!current()) return;
        setWindowLabel(`${date(page.window_start)} – ${date(page.window_end)}`);
        setEvents(old => next ? [...old, ...page.items] : page.items); setCursor(page.next_cursor ?? undefined);
      } catch { if (!current()) return; setActivityError(true); }
      if (!next) {
        const [m, j] = await Promise.all([
          collectPages(offset => getAdminMeetings(accessToken, offset), row => row.id),
          collectPages(offset => getRecordingJobs(accessToken, undefined, pageSize, offset), row => row.job_id),
        ]);
        if (!current()) return;
        setMeetings(m); setJobs(j); setSelected(current => current ? m.find(row => row.id === current.id) || (j.some(job => job.job_id === current.id) ? current : null) : null);
      }
    } catch { if (current()) setError("Records could not be loaded. Please retry."); }
    finally { if (current()) setBusy(false); }
  }
  useEffect(() => { void load(); }, [accessToken]); // Explicit Search applies actor filters.
  async function open(m: AdminMeetingOut) {
    const request = ++contentRequest.current;
    detailFiltersRef.current = { from: auditFiltersRef.current.from, to: auditFiltersRef.current.to };
    setDetailEvents([]); setDetailCursor(undefined); setDetailWindow(""); void loadDetailActivity();
    setSelected(m); setContent(null); setDetailError(""); try { if (!meetings.some(row => row.id === m.id)) { setDetailError("This recording has no available meeting content. See its processing job below."); return; } const result = await getMeeting(m.id, accessToken); if (request === contentRequest.current) setContent(result); } catch { if (request === contentRequest.current) setDetailError("Meeting content could not be loaded. It may be unavailable or access may be restricted. Retry to check."); } }
  const related = (e: AuditEvent, m: AdminMeetingOut) => e.meeting_id === m.id || e.resource_id === m.id || (content?.id === m.id && content.action_items.some(a => a.id === e.resource_id)) || jobs.some(j => (j.meeting_id === m.id || j.job_id === m.id) && (e.job_id === j.job_id || e.resource_id === j.drive_item_id || e.resource_id === j.job_id));
  const records: AdminMeetingOut[] = [...meetings, ...jobs.filter(j => !j.meeting_id || !meetings.some(m => m.id === j.meeting_id)).map(j => ({ id: j.job_id, title: j.title, recorded_at: null, organizer_upn: null, owner_upn: j.owner_upn || null, meeting_status: "Meeting not available", recording_status: "tracked" as const, job_status: j.status, request_status: null, access: [] }))];
  const rows = records.filter(m => {
    const linked = jobs.filter(j => (j.meeting_id === m.id || j.job_id === m.id));
    const recorded = parseInstant(recordDate(m));
    return (!query || [m.title, m.id, m.owner_upn, m.organizer_upn, ...linked.flatMap(j => [j.job_id, j.drive_item_id, j.title])].join(" ").toLowerCase().includes(query.toLowerCase())) && (!status || m.meeting_status === status || m.job_status === status) && (!start || !!recorded && recorded >= start) && (!end || !!recorded && recorded < end) && (!appliedActor || events.some(e => related(e, m)));
  });
  const linkedJobs = selected ? jobs.filter(job => job.meeting_id === selected.id || job.job_id === selected.id) : [];
  const linkedEvents = selected ? detailEvents.filter(entry => related(entry, selected)).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)) : [];
  const aiEvents = linkedEvents.filter(entry => entry.event_type.startsWith("ai."));
  const evidenceUnavailable = detailBusy ? "Activity evidence is loading." : detailActivityError ? "Activity evidence could not be loaded." : null;
  const sections = ["Meeting & recording", "Processing & AI", "Review & actions", "Access", "Activity & email"];
  return <section className="admin-workspace space-y-4 mb-6 min-w-0 [overflow-wrap:anywhere]">
    {!busy && !error && <div className="admin-overview"><div><strong>{jobs.filter(j => j.status === "failed" || j.is_stuck).length}</strong>Failed or stuck processing</div><div><strong>{meetings.filter(m => m.meeting_status === "awaiting_review").length}</strong>Awaiting review</div></div>}
    <section className="admin-card"><header className="admin-card-header"><h2>Find a record</h2><span>Meetings, recordings &amp; activity</span></header><form onSubmit={e => {
      e.preventDefault();
      setDateSearchAttempted(true);
      if (fromError || toError) return;
      setAppliedActor(actor);
      const dates = {from, to};
      setAppliedDates(dates);
      void load(undefined, actor, dates);
    }} className="admin-filter-grid">
      <label>Record, ID or owner<input className={input} value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>Actor email or system ID<input className={input} value={actor} onChange={e => setActor(e.target.value)} /></label>
      <CalendarDateField id="admin-record-from" label="From (Johannesburg)" value={from} onChange={setFrom}
        error={dateSearchAttempted ? fromError : undefined} />
      <CalendarDateField id="admin-record-to" label="To (Johannesburg)" value={to} onChange={setTo}
        error={dateSearchAttempted ? toError : undefined} />
      <div className="col-span-full space-y-2">
        <p role="status">Applied dates: {appliedDates.from || appliedDates.to ? `${appliedDates.from || "Any earlier date"} to ${appliedDates.to || "Any later date"}` : "No date limits"} · Johannesburg time</p>
        {(from !== appliedDates.from || to !== appliedDates.to) && <p>Select Search to apply the date changes.</p>}
      </div>
      <label>Status<select className={input} value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{Array.from(new Set(meetings.flatMap(m => [m.meeting_status, m.job_status]).filter(Boolean))).map(s => <option key={s} value={s!}>{readable(s!)}</option>)}</select></label>
      <div className="admin-filter-actions"><button className="admin-primary" type="submit" disabled={busy}>Search</button><button type="button" onClick={() => { setQuery(""); setActor(""); setAppliedActor(""); setStatus(""); setFrom(""); setTo(""); setDateSearchAttempted(false); setAppliedDates({from: "", to: ""}); void load(undefined, "", {from: "", to: ""}); }}>Refresh default view</button><button type="button" onClick={() => { setQuery(""); setActor(""); setStatus(""); setFrom(""); setTo(""); setDateSearchAttempted(false); setAppliedActor(""); setSelected(null); setAppliedDates({from: "", to: ""}); void load(undefined, "", {from: "", to: ""}); }}>Reset</button></div>
    </form></section>
    {busy && <p role="status">Loading records…</p>}{error && <p role="alert">{error} <button onClick={() => void load()}>Retry</button></p>}
    <section className="admin-card" aria-labelledby="admin-records"><header className="admin-card-header"><h2 id="admin-records">Meetings &amp; recordings</h2><span>{busy ? "Loading records…" : `${rows.length} results`}</span></header>
    <div tabIndex={0} aria-label="Meeting results" onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "End" || e.key === "Home")) { e.preventDefault(); e.currentTarget.scrollTop = e.key === "End" ? e.currentTarget.scrollHeight : 0; } }} className="admin-scroll">
      <div className="admin-result-columns admin-sticky" aria-hidden="true">{["Meeting / recording","Owner","Date / source","Meeting status","Processing","Attention","Details"].map((v,i)=><span key={i}>{v}</span>)}</div>
      {rows.map(m => <article key={m.id} className="admin-result-row"><strong title={m.title || "Untitled meeting"}>{m.title || "Untitled meeting"}</strong><span className="admin-muted">{m.owner_upn || m.organizer_upn || "Owner not recorded"}</span><div><span>{date(recordDate(m))}</span><p className="admin-muted">{recordDate(m) ? (m.card_date?.source === "meeting" ? "Meeting date" : "Recording date") : "Date source unavailable"}</p></div><AdminStatus value={m.meeting_status}/><AdminStatus value={m.job_status || "Not recorded"}/><span className="admin-muted">{m.job_status === "failed" ? "Processing needs attention" : jobs.some(j => j.meeting_id===m.id && j.is_stuck) ? "Processing may be stuck" : "—"}</span><button onClick={e => { setDetailOpener(e.currentTarget); void open(m); }}>Details</button></article>)}
      {!busy && !error && !rows.length && <p className="admin-empty">No matching records in the loaded range.</p>}
    </div><footer className="admin-card-footer"><span>{meetings.length} meetings / {jobs.length} jobs loaded · {rows.length} matching records</span><span>{busy ? "Reading API pages…" : error ? "Loading incomplete — retry above" : "All record pages loaded"} · Johannesburg time</span></footer></section>
    {activityError && <p role="alert">Activity could not be loaded. Meeting results use their own date range. <button type="button" onClick={() => void load()}>Retry activity</button></p>}
    {appliedActor && <div tabIndex={0} className="max-h-96 overflow-y-auto"><h2>Actor activity across meetings (loaded audit pages)</h2>{events.map(e => <button className="block p-2 text-left" key={e.id} onClick={() => setEvent(e)}>{date(e.occurred_at)} · {e.event_type} · {e.outcome} · {e.meeting_id || e.resource_id}</button>)}</div>}
    <div className="admin-card-footer"><span>{events.length} activity records loaded · {cursor ? "More available" : "No more in the queried window"}</span>{cursor && <button disabled={busy} onClick={() => void load(cursor)}>Load more activity</button>}<details><summary>Search scope</summary><p>Meeting and job search includes every API page. Activity uses a separate window: 7 days by default, up to 90 days from a selected start date. Counts refer to loaded records.</p><p>{windowLabel}</p></details></div>
    {selected && <AdminModal title={selected.title || "Meeting details"} status={<AdminStatus value={content?.state || selected.meeting_status}/>}
      onClose={() => setSelected(null)} opener={detailOpener} bodyRef={detailBody} navigation={
      <nav aria-label="Details sections" className="admin-detail-nav">
        {sections.map((label, index) => <button key={label} type="button" onClick={() => {
          const body = detailBody.current;
          const heading = body?.querySelector<HTMLElement>(`[data-detail-section="${index}"] > h3`);
          if (!body || !heading) return;
          heading.focus({ preventScroll: true });
          const offset = heading.getBoundingClientRect().top - body.getBoundingClientRect().top;
          body.scrollTop = Math.floor(body.scrollTop + offset);
        }}>{label}</button>)}
      </nav>
    }>
      <div className="admin-detail-card space-y-4 [&_main]:p-0 [&_main]:max-w-none [&_main>a]:hidden [&_table]:max-sm:block [&_table]:max-sm:min-w-0 [&_thead]:max-sm:hidden [&_tbody]:max-sm:block [&_tr]:max-sm:block [&_td]:max-sm:block [&_td]:max-sm:whitespace-normal">
        <section data-detail-section="0">
          <h3 tabIndex={-1} className="admin-section-title">{sections[0]}</h3>
          <p>Organiser: {content?.organizer_upn || selected.organizer_upn || "Not recorded"}</p><p>Owner: {selected.owner_upn || "Not recorded"}</p>
          <p>Participants: {content ? content.calendar_participants.map(p => p.name).join(", ") || "No verified participant records" : detailError ? "Participant data unavailable" : "Loading participant data…"}</p>
          <p>Meeting time: {selected.card_date?.source === "meeting" ? `${date(selected.card_date.value)} · ${selected.card_date.reason || "meeting date metadata"}` : "No verified meeting time"}</p>
          <p>Recording time: {selected.card_date?.source === "recording" && selected.card_date.value ? `${date(selected.card_date.value)} · recording metadata` : "No separately verified recording time"}</p><p>Recording link: {selected.recording_status === "tracked" ? "Tracked" : "Not verified"}</p>
          <p>{linkedJobs.length ? `${linkedJobs.length} linked processing jobs` : "No verified job link in loaded records"}</p>
          <details><summary>Reference IDs</summary><p>Record: {selected.id}</p>{selected.card_date?.event_id && <p>Calendar event: {selected.card_date.event_id}</p>}{linkedJobs.map(job => <p key={job.job_id}>Recording: {job.drive_item_id} · Job: {job.job_id}</p>)}</details>
        </section>
        <section data-detail-section="1">
          <h3 tabIndex={-1} className="admin-section-title">{sections[1]}</h3>
          {!linkedJobs.length && <p>No verified processing job in loaded records.</p>}
          {linkedJobs.map(job => <div key={job.job_id}><AdminStatus value={job.status}/>{job.status === "failed" && <p>Failure: {job.failure ? `${job.failure.stage} · ${job.failure.category}` : "Reason not verified"}</p>}<details><summary>Attempt details</summary><p>{job.attempts} of {job.max_attempts} attempts. Job timestamps and retry schedule are not exposed by this response.</p></details></div>)}
          <p>{content?.transcript || content?.summary ? "Saved results are available from the meeting API." : content ? "No saved transcript or summary in the meeting response." : "Saved results have not been loaded."}</p>
          <p>{aiEvents.length ? "Verified AI events and their recorded times:" : evidenceUnavailable || "No verified AI call found in the loaded activity window. Result generation time and model cannot be inferred."}</p>
          {aiEvents.map(entry => <p key={entry.id}>{eventTitle(entry.event_type)} · {date(entry.occurred_at)}</p>)}
        </section>
        <section data-detail-section="2">
          <h3 tabIndex={-1} className="admin-section-title">{sections[2]}</h3>
          {content && <p>Review status: {readable(content.state)}</p>}
          {detailError ? <p role="alert">{detailError} <button onClick={() => void open(selected)}>Retry content</button></p> : content ? <MeetingDetailClient meeting={content} upn={callerUpn} accessToken={accessToken}/> : <p role="status">Loading review content…</p>}
        </section>
        <section data-detail-section="3">
          <h3 tabIndex={-1} className="admin-section-title">{sections[3]}</h3>
          {selected.access.length ? <ul>{selected.access.map(person => <li key={person.user_upn}>
            {person.user_upn} · {person.is_organizer ? "Organiser" : person.edit_access ? "View and edit" : "View"}
          </li>)}</ul> : <p>No verified access records.</p>}
        </section>
        <section data-detail-section="4">
          <h3 tabIndex={-1} className="admin-section-title">{sections[4]}</h3>
          {detailBusy && <p role="status">Loading activity…</p>}
          {detailActivityError && <p role="alert">{detailActivityError} <button onClick={() => void loadDetailActivity(detailCursor)}>Retry Details activity</button></p>}
          {detailWindow && <p>{detailWindow} · {linkedEvents.length} linked / {detailEvents.length} total activity records loaded · {detailCursor ? "More available" : "No more in this window"}</p>}
          {!detailBusy && !detailActivityError && !linkedEvents.length && <p>No verified linked activity found in the loaded query window.</p>}
          <p>Approval records review. Email submission records a request or Graph acceptance. Neither confirms delivery.</p>
          {linkedEvents.length > 0 && <div tabIndex={0} aria-label="Linked activity" className="max-h-96 overflow-y-auto">
            {linkedEvents.map(entry => <article key={entry.id} className="border-b py-2"><strong>{eventTitle(entry.event_type)}</strong><p>{date(entry.occurred_at)} · {entry.actor_upn || entry.actor_id}</p><p>{outcomeDescription(entry)}</p>{typeof entry.metadata.content_revision === "string" && <p>Version {typeof entry.metadata.previous_revision === "string" ? entry.metadata.previous_revision.slice(0, 8) : "original"} → {entry.metadata.content_revision.slice(0, 8)}</p>}<AuditEventDialog event={entry}/></article>)}
          </div>}
          {detailCursor && <button disabled={detailBusy} onClick={() => void loadDetailActivity(detailCursor)}>Load more activity for Details</button>}
        </section>
      </div>
    </AdminModal>}
    {!selected && event && <div><button onClick={() => setEvent(null)}>Close activity selection</button><AuditEventDialog event={event} /></div>}
  </section>;
}
