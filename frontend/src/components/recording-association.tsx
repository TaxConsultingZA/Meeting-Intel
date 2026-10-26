"use client";
import { useState } from "react";
import { getRecordingCalendarChoices, setRecordingAssociation, type RecordingCalendarChoice } from "@/lib/api";
import type { AvailableRecording } from "@/lib/types";

export default function RecordingAssociation({ recording, token, onSaved }: {
  recording: AvailableRecording; token: string; onSaved: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [choices, setChoices] = useState<RecordingCalendarChoice[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = recording.job?.status === "pending" || recording.job?.status === "processing";

  async function show() {
    setOpen(true); setBusy(true); setError(null);
    try {
      setChoices(await getRecordingCalendarChoices(token, recording.drive_id, recording.drive_item_id));
    } catch {
      setError("Calendar choices unavailable. Check your access or keep this recording independent.");
    } finally { setBusy(false); }
  }
  async function save(eventId: string | null) {
    setBusy(true); setError(null);
    try {
      await setRecordingAssociation(token, recording.drive_id, recording.drive_item_id, eventId);
      await onSaved(); setOpen(false);
    } catch {
      setError("Unable to save. Only the recording owner can change this link after active processing finishes.");
    } finally { setBusy(false); }
  }
  if (!open) return <button type="button" disabled={active} onClick={() => void show()}
    className="mt-1 text-xs text-blue-700 underline disabled:opacity-50">Manage calendar link</button>;
  return <div className="mt-2 space-y-2 text-xs">
    <p>Choose your calendar event. Linking preserves results and does not share the recording.</p>
    <label className="block">Calendar event
      <select aria-label="Calendar event" className="block w-full border p-1" value={selected}
        onChange={e => setSelected(e.target.value)} disabled={busy}>
        <option value="">Select a specific event</option>
        {choices.map(e => <option key={e.id} value={e.id}>
          {e.subject || "Untitled event"} — {e.start.dateTime} ({e.start.timeZone}){e.isCancelled ? " — Cancelled" : ""}
        </option>)}
      </select>
    </label>
    {choices.length === 0 && !busy && <p>No calendar choices in the recording's date window.</p>}
    <button type="button" disabled={busy || !selected} onClick={() => void save(selected)} className="mr-3 underline">Link selected event</button>
    <button type="button" disabled={busy} onClick={() => void save(null)} className="mr-3 underline">Keep independent</button>
    <button type="button" disabled={busy} onClick={() => setOpen(false)} className="underline">Close link editor</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}
