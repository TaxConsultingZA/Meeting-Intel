"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import LoadingSpinner from "@/components/loading-spinner";
import { ApiError, getMeetingDecisions, saveMeetingDecisions } from "@/lib/api";
import type { MeetingDecision, MeetingDecisionInput } from "@/lib/types";

type Props = {
  meetingId: string; meetingTitle: string | null; token: string; canEdit: boolean; disabled?: boolean;
  onPendingChange: (pending: boolean) => void; onSaved: () => void;
};
const control = "rounded-md border border-[#dde1e8] px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-[#003366] disabled:opacity-50";

function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value;
}

export default function MeetingDecisions({ meetingId, meetingTitle, token, canEdit, disabled = false, onPendingChange, onSaved }: Props) {
  const [rows, setRows] = useState<MeetingDecision[] | null>(null);
  const [draft, setDraft] = useState<MeetingDecisionInput[]>([]);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const inFlight = useRef(false);
  const editingRef = useRef(false);
  const [draftMeetingId, setDraftMeetingId] = useState(meetingId);
  const [readFailed, setReadFailed] = useState(false);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(() => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    onPendingChange(true);
    return getMeetingDecisions(meetingId, token, controller.signal).then(result => {
      if (!controller.signal.aborted) { setRows(result); setReadFailed(false); setError(""); onPendingChange(editingRef.current); }
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) { setReadFailed(true); setError(failure instanceof ApiError && (failure.status === 401 || failure.status === 403)
        ? "Decisions access could not be confirmed. Your session expired or access was removed. Your unsaved draft is kept; sign in or reload to check access."
        : "Decisions could not be loaded. Any unsaved draft is kept; retry the read before saving."); onPendingChange(true); }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
  }, [meetingId, token, onPendingChange]);
  useEffect(() => { void load(); return () => { request.current?.abort(); }; }, [load]);
  useEffect(() => () => onPendingChange(false), [onPendingChange]);
  useEffect(() => {
    if (!editing) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    const navigate = (event: MouseEvent) => {
      const link = (event.target as Element).closest?.("a[href]");
      if (link && link.getAttribute("href") !== window.location.pathname &&
          !window.confirm("You have an unsaved decisions draft. Leave this meeting and discard it?")) {
        event.preventDefault(); event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", navigate, true);
    return () => { window.removeEventListener("beforeunload", warn); document.removeEventListener("click", navigate, true); };
  }, [editing]);
  function reload() { setLoading(true); setError(""); void load(); }

  function begin() {
    if (readFailed || loading || !canEdit) return;
    setDraft(rows?.length ? rows.map(({ id, content, decision_date }) => ({ id, content, decision_date })) : [{ content: "", decision_date: "" }]);
    editingRef.current = true; setDraftMeetingId(meetingId);
    setEditing(true); setError(""); setSaved(false); onPendingChange(true);
  }
  function cancel() { editingRef.current = false; setEditing(false); if (!readFailed) setError(""); onPendingChange(readFailed || loading); }
  async function save() {
    if (inFlight.current || !canEdit || disabled || draftMeetingId !== meetingId || loading || readFailed) return;
    const invalid = draft.findIndex(entry => !entry.content.trim() || !validDate(entry.decision_date));
    if (invalid >= 0) {
      setError(`Decision ${invalid + 1} needs content and a valid date.`);
      return;
    }
    request.current?.abort();
    inFlight.current = true; setSaving(true); setError("");
    try {
      const result = await saveMeetingDecisions(meetingId, draft, token);
      editingRef.current = false; setRows(result); setEditing(false); setSaved(true); onPendingChange(false); onSaved();
    } catch {
      setError("Decisions could not be saved. Your access or meeting status may have changed. Keep your draft and reload the meeting to check.");
    } finally { inFlight.current = false; setSaving(false); }
  }

  return <section aria-label="Meeting decisions" className="min-w-0 overflow-hidden rounded-lg border border-[#dde1e8] bg-white shadow-sm">
    <div className="border-b-[3px] border-[#C9A52C] bg-[#003366] px-5 py-3">
      <h2 className="text-[15px] font-semibold text-white">Meeting Decisions</h2>
    </div>
    <div className="min-w-0 space-y-3 break-words p-5">
      <p className="text-xs text-[#6b7280]">Human-entered decisions for this meeting. Participants are not inferred. Editing follows the existing note-review permissions and locks after approval.</p>
      <Link href={`/meetings/${encodeURIComponent(meetingId)}`} className="text-sm font-medium text-[#003366] underline">{meetingTitle?.trim() || "Related meeting"}</Link>
      {loading && <LoadingSpinner label="Decisions loading" />}
      {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {!loading && (rows === null || readFailed) && <button className={control} onClick={reload}>Reload decisions</button>}
      {saved && <p role="status" className="text-sm text-[#003366]">Decisions saved.</p>}
      {editing && (!canEdit || draftMeetingId !== meetingId) && <p role="alert" className="text-sm text-amber-900">{draftMeetingId !== meetingId ? "Meeting changed. This draft belongs to the previous meeting and cannot be saved here." : "Edit access is no longer available or this meeting is locked. Your unsaved draft is still shown below; copy it before leaving."}</p>}
      {editing ? <form aria-label="Edit meeting decisions" onSubmit={event => { event.preventDefault(); void save(); }} className="space-y-4">
        <fieldset disabled={saving || disabled} className="min-w-0 space-y-4">
          {draft.map((entry, index) => <div key={entry.id ?? index} className="grid min-w-0 grid-cols-1 gap-2 rounded-md border border-[#dde1e8] bg-[#fafbfc] p-3">
            <label className="flex min-w-0 flex-col gap-1 text-sm">Decision {index + 1} content
              <textarea readOnly={!canEdit || draftMeetingId !== meetingId} required maxLength={2000} rows={3} className={`${control} min-w-0 w-full bg-white`} value={entry.content} onChange={event => setDraft(current => current.map((item, i) => i === index ? { ...item, content: event.target.value } : item))} />
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-sm">Decision {index + 1} date
              <input readOnly={!canEdit || draftMeetingId !== meetingId} required type="date" className={`${control} min-w-0 w-full bg-white`} value={entry.decision_date} onChange={event => setDraft(current => current.map((item, i) => i === index ? { ...item, decision_date: event.target.value } : item))} />
            </label>
            <button type="button" disabled={!canEdit || draftMeetingId !== meetingId} className={`${control} justify-self-start text-red-800`} onClick={() => setDraft(current => current.filter((_, i) => i !== index))}>Remove decision {index + 1}</button>
          </div>)}
          <div className="flex flex-wrap gap-2">
            <button type="button" className={control} disabled={!canEdit || draftMeetingId !== meetingId || draft.length >= 50} onClick={() => setDraft(current => [...current, { content: "", decision_date: "" }])}>Add decision</button>
            <button type="submit" disabled={!canEdit || draftMeetingId !== meetingId || loading || readFailed} className={`${control} bg-[#003366] font-semibold text-white`}>{saving ? "Saving decisions…" : "Save decisions"}</button>
            <button type="button" className={control} onClick={cancel}>Cancel</button>
          </div>
        </fieldset>
      </form> : <>
        {rows?.length === 0 && <p className="text-sm text-[#6b7280]">No decisions recorded.</p>}
        <ul className="space-y-3">{rows?.map(row => <li key={row.id} className="min-w-0 rounded-md border border-[#dde1e8] bg-[#fafbfc] p-3">
          <p className="whitespace-pre-wrap text-sm leading-6">{row.content}</p>
          <p className="mt-1 text-xs text-[#6b7280]">Decision date: <time dateTime={row.decision_date}>{row.decision_date}</time></p>
        </li>)}</ul>
        {canEdit && rows !== null && <button className={`${control} font-semibold text-[#003366]`} disabled={disabled || loading || readFailed} onClick={begin}>Edit decisions</button>}
      </>}
    </div>
  </section>;
}
