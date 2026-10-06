"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, RefreshCw, Search, History, AlertCircle } from "lucide-react";
import { ApiError, getAuditEvents } from "@/lib/api";
import type { AuditEventsPage, AuditFilters, AuditOutcome } from "@/lib/types";
import LocalDateTime, { useUserTimeZone } from "@/components/local-date-time";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import AuditEventDialog from "./audit-event-dialog";
import { actionLabels, actorLabel, OutcomeBadge } from "./audit-display";

type Draft = { from: string; to: string; event_type: string; outcome: AuditOutcome | ""; actor: string };
type Request = { filters: AuditFilters; window?: { from: string; to: string }; cursors: (string | undefined)[]; index: number; refresh: boolean };
const emptyDraft: Draft = { from: "", to: "", event_type: "", outcome: "", actor: "" };
const inputStyle = "w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]";
const secondaryStyle = "rounded-md border-[#dde1e8] text-[#003366] text-[13px]";
const cellStyle = "px-4 py-2.5 border border-[#dde1e8] text-[12px]";

export function parseAuditDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const [, year, month, day, hour, minute] = match.map(Number);
  const date = new Date(0);
  date.setFullYear(year, month - 1, day);
  date.setHours(hour, minute, 0, 0);
  // Reject calendar overflow and local times that do not exist during DST.
  return date.getFullYear() === year && date.getMonth() === month - 1 &&
    date.getDate() === day && date.getHours() === hour && date.getMinutes() === minute ? date : null;
}

export default function AuditLogsClient({ accessToken }: { accessToken: string }) {
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const [request, setRequest] = useState<Request>({ filters: {}, cursors: [undefined], index: 0, refresh: false });
  const [result, setResult] = useState<{ request: Request; token: string; page: AuditEventsPage | null; error: string | null } | null>(null);
  const zone = useUserTimeZone();
  const loading = result?.request !== request || result?.token !== accessToken;
  const page = result?.token === accessToken && (!loading || request.refresh) ? result.page : null;
  const error = !loading ? result?.error : null;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    getAuditEvents(accessToken, { ...request.filters, ...request.window }, request.cursors[request.index], controller.signal)
      .then((page) => { if (active) setResult({ request, token: accessToken, page, error: null }); })
      .catch((cause: unknown) => {
        if (!active) return;
        const status = cause instanceof ApiError ? cause.status : null;
        const error = status === 401 ? "Your session has expired. Please sign in again."
          : status === 403 ? "Admin access is required to view audit logs."
          : status === 422 ? "The audit query is invalid. Check the filters or reset them."
          : "Unable to load audit events. Please try again.";
        setResult({ request, token: accessToken, page: null, error });
      });
    return () => { active = false; controller.abort(); };
  }, [accessToken, request]);

  function apply() {
    const from = draft.from.trim() ? parseAuditDate(draft.from) : null;
    const to = draft.to.trim() ? parseAuditDate(draft.to) : null;
    if ((draft.from.trim() && !from) || (draft.to.trim() && !to)) {
      setFormError("Enter a valid date and time as YYYY-MM-DD HH:mm (24-hour time).");
      return;
    }
    const end = to ?? new Date();
    if ((from && !Number.isFinite(from.getTime())) || (to && !Number.isFinite(to.getTime())) ||
        (from && (from >= end || end.getTime() - from.getTime() > 90 * 86400000))) {
      setFormError("Choose a positive date range of at most 90 days.");
      return;
    }
    const actor = draft.actor.trim();
    if (actor && !(actor.includes("@") ? /^[^\s@]+@[^\s@]+$/.test(actor) && actor.length <= 255 : /^[a-zA-Z0-9_-]{1,64}$/.test(actor))) {
      setFormError("Enter an actor email, user ID, or system ID such as recording_worker.");
      return;
    }
    setFormError(null);
    const filters: AuditFilters = {};
    if (from) filters.from = from.toISOString();
    if (to) filters.to = to.toISOString();
    if (draft.event_type) filters.event_type = draft.event_type;
    if (draft.outcome) filters.outcome = draft.outcome;
    if (actor) {
      if (actor.includes("@")) filters.actor_upn = actor.toLowerCase();
      else filters.actor_id = actor;
    }
    setRequest({ filters, cursors: [undefined], index: 0, refresh: false });
  }

  function reset() {
    setDraft(emptyDraft);
    setFormError(null);
    setRequest({ filters: {}, cursors: [undefined], index: 0, refresh: false });
  }

  return <main className="max-w-5xl mx-auto px-6 py-7">
    <header className="mb-6">
      <h1 className="text-[22px] font-bold text-[#003366]">Audit Logs</h1>
      <p className="text-[#6b7280] text-[13.5px] mt-0.5">Review recording activity, email approvals, and sending outcomes.</p>
      <Link href="/admin" className="mt-2 inline-block text-[13px] font-semibold text-[#003366] hover:underline">Back to Administration</Link>
    </header>

    <section aria-labelledby="audit-filters" className="mb-3 bg-white rounded-lg border border-[#dde1e8] shadow-sm p-4">
      <h2 id="audit-filters" className="text-sm font-semibold text-[#003366] mb-3">Filters</h2>
      <form onSubmit={(event) => { event.preventDefault(); apply(); }}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="flex flex-col gap-1.5 text-[12.5px] font-medium text-[#374151]">From
            <input type="text" lang="en-ZA" placeholder="YYYY-MM-DD HH:mm" aria-describedby="audit-date-help" className={inputStyle} value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1.5 text-[12.5px] font-medium text-[#374151]">To (exclusive)
            <input type="text" lang="en-ZA" placeholder="YYYY-MM-DD HH:mm" aria-describedby="audit-date-help" className={inputStyle} value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1.5 text-[12.5px] font-medium text-[#374151]">Event type
            <select className={inputStyle} value={draft.event_type} onChange={(e) => setDraft({ ...draft, event_type: e.target.value })}>
              <option value="">All events</option>{["recording", "email"].map((group) => <optgroup key={group} label={group === "recording" ? "Recording activity" : "Email approval & sending"}>{Object.entries(actionLabels).filter(([value]) => value.startsWith(`${group}.`)).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</optgroup>)}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 text-[12.5px] font-medium text-[#374151]">Outcome
            <select className={inputStyle} value={draft.outcome} onChange={(e) => setDraft({ ...draft, outcome: e.target.value as Draft["outcome"] })}>
              <option value="">All outcomes</option>{["requested", "succeeded", "failed", "unknown"].map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 text-[12.5px] font-medium text-[#374151] sm:col-span-2 lg:col-span-2">Actor
            <input className={inputStyle} aria-describedby="audit-actor-help" value={draft.actor} placeholder="Email address, user ID, or system ID" onChange={(e) => setDraft({ ...draft, actor: e.target.value })} />
          </label>
        </div>
        <p id="audit-date-help" className="mt-3 text-xs text-[#6b7280]">Use YYYY-MM-DD HH:mm, for example 2026-10-06 14:30. Dates use {zone ?? "your local timezone"}. The end time is excluded. Default: last 7 days. Maximum range: 90 days.</p>
        <p id="audit-actor-help" className="mt-2 text-xs text-[#6b7280]">Actor matches exactly. Use an approver’s full email address, or recording_worker / email_sender for system activity.</p>
        {formError && <p role="alert" className="mt-3 text-xs text-red-700">{formError}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="submit" className="rounded-md bg-[#003366] hover:bg-[#0a4a8c] text-white text-[13px] font-semibold px-4"><Search size={14} aria-hidden="true" />Apply</Button>
          <Button type="button" variant="outline" className={secondaryStyle} onClick={reset}>Reset</Button>
          <Button type="button" variant="outline" className={`${secondaryStyle} bg-[#f8fafc] hover:bg-blue-50 font-semibold`} title="Reload the applied filters from the first page" disabled={loading} onClick={() => setRequest({ ...request, window: undefined, cursors: [undefined], index: 0, refresh: request.index === 0 })}><RefreshCw size={14} aria-hidden="true" />Refresh</Button>
        </div>
      </form>
      <div aria-label="Active filters" className="mt-4 border-t border-[#dde1e8] pt-3 text-xs text-[#6b7280]">
        <p className="mb-2 font-semibold text-[#003366]">Active filters</p>
        <ul className="flex flex-wrap gap-2">
          <li className="rounded-md border border-[#dde1e8] bg-[#f8fafc] px-2 py-1">Event: {request.filters.event_type ? actionLabels[request.filters.event_type] ?? request.filters.event_type : "All events"}</li>
          <li className="rounded-md border border-[#dde1e8] bg-[#f8fafc] px-2 py-1">Outcome: {request.filters.outcome ? request.filters.outcome[0].toUpperCase() + request.filters.outcome.slice(1) : "All outcomes"}</li>
          <li className="rounded-md border border-[#dde1e8] bg-[#f8fafc] px-2 py-1 break-all">Actor: {request.filters.actor_upn ?? request.filters.actor_id ?? "All actors"}</li>
          <li className="rounded-md border border-[#dde1e8] bg-[#f8fafc] px-2 py-1">{request.filters.from || request.filters.to ? <>
            From {request.filters.from ? <LocalDateTime value={request.filters.from} /> : "7 days before end"} to {request.filters.to ? <LocalDateTime value={request.filters.to} /> : "now"} (exclusive)
          </> : "Date range: Last 7 days"}</li>
        </ul>
      </div>
    </section>

    <section aria-labelledby="audit-events" aria-busy={loading} className="bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
      <div className="px-4 py-3"><div className="flex flex-wrap items-center justify-between gap-2"><h2 id="audit-events" className="text-sm font-semibold text-[#003366]">Audit Events</h2>
        {!loading && page && <span className="rounded-md border border-[#dde1e8] bg-[#f8fafc] px-2 py-1 text-xs font-medium text-[#003366]">{page.items.length} {page.items.length === 1 ? "record" : "records"} on this page</span>}
      </div>
        {page && <p className="mt-1 text-xs text-[#6b7280]">Window: <LocalDateTime value={page.window_start} /> – <LocalDateTime value={page.window_end} /></p>}
      </div>
      <p className="px-4 pb-3 text-xs text-[#6b7280]">Newest first. Email submission succeeded means Graph accepted the request; delivery is not confirmed.</p>
      <Table className="text-xs min-w-[720px]" aria-label="Audit events">
        <TableHeader><TableRow className="hover:bg-transparent">{["Time", "Actor", "Action", "Resource", "Outcome", "Details"].map((label) => <TableHead key={label} scope="col" className="bg-[#003366] text-white text-xs font-semibold px-4 py-2.5 border border-white/10">{label}</TableHead>)}</TableRow></TableHeader>
        <TableBody>
          {loading && <TableRow><TableCell colSpan={6} className="px-4 py-8 text-center"><p role="status" className="flex justify-center items-center gap-2 text-sm text-[#6b7280]"><Loader2 size={18} className="animate-spin" aria-hidden="true" />{page ? "Refreshing…" : "Loading audit events…"}</p></TableCell></TableRow>}
          {error && <TableRow><TableCell colSpan={6} className="px-4 py-8 text-center bg-red-50/50"><div role="alert" className="text-[13px] text-red-700"><AlertCircle size={20} className="mx-auto mb-2" aria-hidden="true" /><p className="font-semibold">Audit events could not be loaded</p><p className="mt-1">{error}</p></div><Button variant="outline" className={`${secondaryStyle} mt-3 bg-white`} onClick={() => setRequest({ ...request, refresh: false })}>Retry</Button></TableCell></TableRow>}
          {page?.items.map((event, index) => <TableRow key={event.id} className={`${index % 2 ? "bg-[#f8fafc]" : ""} hover:bg-blue-50/30`}>
            <TableCell className={`${cellStyle} text-[#6b7280]`}><LocalDateTime value={event.occurred_at} /></TableCell>
            <TableCell className={`${cellStyle} whitespace-normal break-words max-w-48`}>{actorLabel(event)}</TableCell>
            <TableCell className={`${cellStyle} whitespace-normal`}>{actionLabels[event.event_type] ?? event.event_type}</TableCell>
            <TableCell className={cellStyle}><span className="block">{event.resource_type.replaceAll("_", " ")}</span><span className="text-[#6b7280]" title={event.resource_id}>{event.resource_id.slice(0, 8)}…</span></TableCell>
            <TableCell className={cellStyle}><OutcomeBadge outcome={event.outcome} />{event.outcome === "failed" && event.metadata.retry_scheduled === true && <span className="block mt-1 text-[#6b7280]">Retry scheduled</span>}{event.metadata.reason === "existing_result_preserved" && <span className="block mt-1 text-[#6b7280]">Existing result preserved</span>}</TableCell>
            <TableCell className={cellStyle}><AuditEventDialog event={event} /></TableCell>
          </TableRow>)}
          {!loading && !error && page?.items.length === 0 && <TableRow><TableCell colSpan={6} className="px-4 py-10 text-center text-[#6b7280] text-[13px]"><History size={22} className="mx-auto mb-3 text-[#003366]" aria-hidden="true" /><p className="font-semibold text-[#003366]">No audit events match these filters.</p><p className="mt-1">Try a wider date range or reset the filters to the last 7 days.</p><Button variant="outline" className={`${secondaryStyle} mt-3`} onClick={reset}>Clear filters</Button></TableCell></TableRow>}
        </TableBody>
      </Table>
      <div className="px-4 py-3 flex flex-wrap items-center justify-between gap-3 border-t border-[#dde1e8]">
        <span className="text-xs text-[#6b7280]">Page {request.index + 1}{page ? ` · ${page.items.length} events` : ""}</span>
        <div className="flex gap-2">
          <Button variant="outline" className={secondaryStyle} disabled={loading || request.index === 0} onClick={() => setRequest({ ...request, index: request.index - 1, refresh: false })}>Previous</Button>
          <Button variant="outline" className={secondaryStyle} disabled={loading || !page?.has_more || !page.next_cursor} onClick={() => {
            if (!page?.next_cursor) return;
            setRequest({ ...request, window: { from: page.window_start, to: page.window_end }, cursors: [...request.cursors.slice(0, request.index + 1), page.next_cursor], index: request.index + 1, refresh: false });
          }}>Next</Button>
        </div>
      </div>
    </section>
  </main>;
}
