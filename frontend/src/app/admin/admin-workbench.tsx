"use client";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { getAdminMeetings, getRecordingJobs, getAuditEvents, getMeeting } from "@/lib/api";
import type { AdminMeetingOut, RecordingJobOut, AuditEvent, AuditFilters, MeetingOut } from "@/lib/types";
import CalendarDateField, { calendarDateError } from "@/components/calendar-date-field";
import { parseInstant } from "@/lib/time";
import MeetingDetailClient from "../meetings/[id]/meeting-detail-client";
import { AdminStatus, readable } from "./access-requests-panel";
import AdminModal from "./admin-modal";
import { eventTitle, outcomeDescription } from "./audit-logs/audit-display";
import AuditEventDialog from "./audit-logs/audit-event-dialog";
const date = (value: string | null) => {
  const instant = parseInstant(value);
  return instant ? instant.toLocaleString("en-ZA", { timeZone: "Africa/Johannesburg" }) : "Date not available";
};
const dayMs = 86400000;
const meetingStatuses = ["queued", "downloading", "transcribing", "extracting", "awaiting_review", "approved", "sent", "failed", "cancelled"];
function bounds({from, to}: {from: string; to: string}) {
  return {
    start: from ? new Date(`${from}T00:00:00+02:00`) : undefined,
    end: to ? new Date(new Date(`${to}T00:00:00+02:00`).getTime() + dayMs) : undefined,
  };
}

const recordDate = (record: AdminMeetingOut) => record.card_date ? record.card_date.value : record.recorded_at;
const input = "w-full min-w-0 rounded border p-2 text-sm";
export default function AdminWorkbench({ accessToken, callerUpn, renderControls, pendingRequests }: { accessToken: string; callerUpn: string; pendingRequests?: number; renderControls?: (meeting: AdminMeetingOut, jobs: RecordingJobOut[], refresh: () => Promise<void>, area: "access" | "processing") => ReactNode }) {
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
  async function load(next?: string, actorValue = appliedActor, dates = appliedDates) {
    const request = ++recordRequest.current;
    const current = () => request === recordRequest.current;
    setBusy(true); setError(""); setActivityError(false);
    if (!next) setEvents([]);
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
        const collected: AuditEvent[] = [];
        const seenCursors = new Set<string>();
        let pageCursor = next;
        do {
          if (pageCursor && seenCursors.has(pageCursor)) throw new Error("Repeated activity cursor");
          if (pageCursor) seenCursors.add(pageCursor);
          const page = await getAuditEvents(accessToken, auditFiltersRef.current, pageCursor);
          collected.push(...page.items);
          pageCursor = actorValue.trim() ? page.next_cursor || undefined : undefined;
        } while (pageCursor && current());
        if (!current()) return;
        setEvents(collected);
      } catch { if (!current()) return; setActivityError(true); }
      if (!next) {
        const m: AdminMeetingOut[] = []; const j: RecordingJobOut[] = [];
        const meetingIds = new Set<string>(), jobIds = new Set<string>();
        for (let offset = 0; ; offset += 200) { const batch = await getAdminMeetings(accessToken, offset); if (!current()) return; if (batch.some(row => meetingIds.has(row.id))) throw new Error("Repeated meeting page"); batch.forEach(row => meetingIds.add(row.id)); m.push(...batch); if (batch.length < 200) break; }
        for (let offset = 0; ; offset += 200) { const batch = await getRecordingJobs(accessToken, undefined, 200, offset); if (!current()) return; if (batch.some(row => jobIds.has(row.job_id))) throw new Error("Repeated job page"); batch.forEach(row => jobIds.add(row.job_id)); j.push(...batch); if (batch.length < 200) break; }
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
  const latestEdit = linkedEvents.find(entry => ["review.reopened", "review.revised"].includes(entry.event_type));
  const reopened = linkedEvents.find(entry => entry.event_type === "review.reopened");
  const currentApproved = content?.state === "approved" || content?.state === "sent";
  const revision = content?.extracted_json?.review_content_revision;
  const evidenceUnavailable = detailBusy ? "Activity evidence is loading." : detailActivityError ? "Activity evidence could not be loaded." : null;
  const sections = ["Meeting & recording", "Processing & AI", "Review & actions", "Access", "Activity & email"];
  return <section className="space-y-4 mb-6 min-w-0 [overflow-wrap:anywhere]">
    {!busy && !error && <div className="admin-overview"><div><strong>{jobs.filter(j => j.status === "failed" || j.is_stuck).length}</strong>Failed or stuck processing</div><div><strong>{meetings.filter(m => m.meeting_status === "awaiting_review").length}</strong>Awaiting review</div>{pendingRequests !== undefined && <div><strong>{pendingRequests}</strong>Pending access requests</div>}</div>}
    <div className="admin-record-workspace"><section><header className="admin-card-header"><h2>Find a record</h2><span>Meetings, recordings &amp; activity</span></header><form onSubmit={e => {
      e.preventDefault();
      setDateSearchAttempted(true);
      if (fromError || toError) return;
      setAppliedActor(actor);
      const dates = {from, to};
      setAppliedDates(dates);
      void load(undefined, actor, dates);
    }} className="admin-filter-grid">
      <label>Record, ID or owner<input autoComplete="off" name="admin-record-search" className={input} value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>Actor email or system ID<input className={input} value={actor} onChange={e => setActor(e.target.value)} /></label>
      <CalendarDateField id="admin-record-from" label="From (Johannesburg)" value={from} onChange={setFrom}
        error={dateSearchAttempted ? fromError : undefined} />
      <CalendarDateField id="admin-record-to" label="To (Johannesburg)" value={to} onChange={setTo}
        error={dateSearchAttempted ? toError : undefined} />
      <div className="col-span-full space-y-2">
        <p role="status">Applied dates: {appliedDates.from || appliedDates.to ? `${appliedDates.from || "Any earlier date"} to ${appliedDates.to || "Any later date"}` : "No date limits"} · Johannesburg time</p>
        {(from !== appliedDates.from || to !== appliedDates.to) && <p>Select Search to apply the date changes.</p>}
      </div>
      <label>Status<select className={input} value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{meetingStatuses.map(s => <option key={s} value={s}>{readable(s)}</option>)}</select></label>
      <div className="admin-filter-actions"><button className="admin-primary" type="submit" disabled={busy}>Search</button><button type="button" onClick={() => { setQuery(""); setActor(""); setAppliedActor(""); setStatus(""); setFrom(""); setTo(""); setDateSearchAttempted(false); setAppliedDates({from: "", to: ""}); void load(undefined, "", {from: "", to: ""}); }}>Refresh default view</button><button type="button" onClick={() => { setQuery(""); setActor(""); setStatus(""); setFrom(""); setTo(""); setDateSearchAttempted(false); setAppliedActor(""); setSelected(null); setAppliedDates({from: "", to: ""}); void load(undefined, "", {from: "", to: ""}); }}>Reset</button></div>
    </form></section>
    {busy && <p role="status">Loading records…</p>}{error && <p role="alert">{error} <button onClick={() => void load()}>Retry</button></p>}
    <section aria-labelledby="admin-records"><header className="admin-card-header"><h2 id="admin-records">Meetings &amp; recordings</h2><span>{busy ? "Loading records…" : `${rows.length} results`}</span></header>
    <div tabIndex={0} aria-label="Meeting results" onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "End" || e.key === "Home")) { e.preventDefault(); e.currentTarget.scrollTop = e.key === "End" ? e.currentTarget.scrollHeight : 0; } }} className="admin-scroll">
      <div className="admin-result-columns admin-sticky" aria-hidden="true">{["Meeting / recording","Owner","Date / source","Meeting status","Processing","Attention","Details"].map((v,i)=><span key={i}>{v}</span>)}</div>
      {rows.map(m => <article key={m.id} className="admin-result-row"><strong title={m.title || "Untitled meeting"}>{m.title || "Untitled meeting"}</strong><span className="admin-muted">{m.owner_upn || m.organizer_upn || "Owner not recorded"}</span><div><span>{date(recordDate(m))}</span><p className="admin-muted">{recordDate(m) ? (m.card_date?.source === "meeting" ? "Meeting date" : "Recording date") : "Date source unavailable"}</p></div><AdminStatus value={m.meeting_status}/><AdminStatus value={m.job_status || "Not recorded"}/><span className="admin-muted">{m.job_status === "failed" ? "Processing needs attention" : jobs.some(j => j.meeting_id===m.id && j.is_stuck) ? "Processing may be stuck" : "—"}</span><button onClick={e => { setDetailOpener(e.currentTarget); void open(m); }}>Details</button></article>)}
      {!busy && !error && !rows.length && <p className="admin-empty">No matching records in the loaded range.</p>}
    </div><footer className="admin-card-footer"><span>{meetings.length} meetings / {jobs.length} jobs loaded · {rows.length} matching records</span><span>{busy ? "Reading API pages…" : error ? "Loading incomplete — retry above" : "All record pages loaded"} · Johannesburg time</span></footer></section></div>
    {activityError && <p role="alert">Activity could not be loaded. Meeting results use their own date range. <button type="button" onClick={() => void load()}>Retry activity</button></p>}
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
          <p>Meeting time: {content?.card_date?.source === "meeting" ? `${date(content.card_date.value)} · ${content.card_date.reason || "meeting date metadata"}` : "No verified meeting time"}</p>
          <p>Recording time: {content?.card_date?.source === "recording" && content.card_date.value ? `${date(content.card_date.value)} · recording metadata` : "No separately verified recording time"}</p><p>Recording link: {selected.recording_status === "tracked" ? "Tracked" : "Not verified"}</p>
          <p>{linkedJobs.length ? `${linkedJobs.length} linked processing jobs` : "No verified job link in loaded records"}</p>
          <details><summary>Reference IDs</summary><p>Record: {selected.id}</p>{content?.card_date?.event_id && <p>Calendar event: {content.card_date.event_id}</p>}{linkedJobs.map(job => <p key={job.job_id}>Recording: {job.drive_item_id} · Job: {job.job_id}</p>)}</details>
        </section>
        <section data-detail-section="1">
          <h3 tabIndex={-1} className="admin-section-title">{sections[1]}</h3>
          {!linkedJobs.length && <p>No verified processing job in loaded records.</p>}
          {linkedJobs.map(job => <div key={job.job_id}><AdminStatus value={job.status}/>{job.status === "failed" && <p>Failure: {job.failure ? `${job.failure.stage} · ${job.failure.category}` : "Reason not verified"}</p>}<details><summary>Attempt details</summary><p>{job.attempts} of {job.max_attempts} attempts. Job timestamps and retry schedule are not exposed by this response.</p></details></div>)}
          {renderControls?.(selected, linkedJobs, () => load(), "processing")}
          <p>{content?.transcript || content?.summary ? "Saved results are available from the meeting API." : content ? "No saved transcript or summary in the meeting response." : "Saved results have not been loaded."}</p>
          <p>{aiEvents.length ? "Verified AI events and their recorded times:" : evidenceUnavailable || "No verified AI call found in the loaded activity window. Result generation time and model cannot be inferred."}</p>
          {aiEvents.map(entry => <p key={entry.id}>{eventTitle(entry.event_type)} · {date(entry.occurred_at)}</p>)}
        </section>
        <section data-detail-section="2">
          <h3 tabIndex={-1} className="admin-section-title">{sections[2]}</h3>
          {content && <p>{revision ? `Version ${revision.slice(0, 8)}` : "Original review version"} · {currentApproved ? "Current content approved" : revision ? "Current content awaits reapproval" : readable(content.state)}</p>}
          <p>{currentApproved && content?.approved_by ? `Approval recorded by ${content.approved_by} · ${content.approved_at ? date(content.approved_at) : "No reliable record"}` : evidenceUnavailable || "Current approval actor: No reliable record."}</p>
          {reopened && <p>Previous content version approved by {String(reopened.metadata.prior_approved_by ?? "No reliable record")} · {typeof reopened.metadata.prior_approved_at === "string" ? date(reopened.metadata.prior_approved_at) : "No reliable record"}</p>}
          <p>{latestEdit ? `Content version changed by ${latestEdit.actor_upn || latestEdit.actor_id} · ${date(latestEdit.occurred_at)}` : "Detailed edit history: No reliable record."}</p>
          {content && <p>{content.email_delivery_status === "sent" ? "Microsoft Graph accepted the email request." : content.email_delivery_status === "sending" ? "Email submission requested. Graph acceptance is unconfirmed." : content.email_delivery_status === "failed" ? "Email submission failed." : content.email_delivery_status === "not_required" || content.state === "awaiting_review" ? "Current version: No email submitted." : "Email submission status: No reliable record."}</p>}
          {detailError ? <p role="alert">{detailError} <button onClick={() => void open(selected)}>Retry content</button></p> : content ? <MeetingDetailClient adminView onReviewChanged={latest => { if (latest) setContent(latest); void load(); void loadDetailActivity(); }} meeting={content} upn={callerUpn} accessToken={accessToken}/> : <p role="status">Loading review content…</p>}
        </section>
        <section data-detail-section="3">
          <h3 tabIndex={-1} className="admin-section-title">{sections[3]}</h3>
          {renderControls?.(selected, linkedJobs, () => load(), "access")}
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
  </section>;
}
