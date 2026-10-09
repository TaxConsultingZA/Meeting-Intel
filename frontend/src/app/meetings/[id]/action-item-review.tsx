"use client";

import { useRef, useState } from "react";
import { editActionItem } from "@/lib/api";
import type { ActionItemEdit, ActionItemOut, Confidence } from "@/lib/types";

function concerns(item: ActionItemOut) {
  return [!item.task.trim() && "Missing task", !item.owner?.trim() && "Missing owner",
    !(item.deadline_iso?.trim() || item.deadline_text?.trim()) && "Missing deadline",
    item.confidence === "low" && "Low confidence"].filter(Boolean) as string[];
}

export default function ActionItemReview({ items, accessToken, canEdit, transcript, onUpdate }: {
  items: ActionItemOut[]; accessToken: string; canEdit: boolean; transcript?: string | null;
  onUpdate: (item: ActionItemOut) => void;
}) {
  if (!items.length) return <p className="text-sm text-gray-500">No action items extracted.</p>;
  const count = items.filter(item => concerns(item).length).length;
  return <div>
    <p className="mb-3 text-sm text-gray-600">{items.length} action item(s) · {count} with review flags. Check each task against its evidence. Flags are guidance; confidence is not approval status.</p>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <caption className="sr-only">Meeting action items and source evidence</caption>
        <thead><tr>{["Task", "Assigned person", "Deadline", "Confidence", "Source evidence"].map(label =>
          <th scope="col" key={label} className="bg-[#003366] px-4 py-3 text-left text-white">{label}</th>)}</tr></thead>
        <tbody>{items.map(item => <ActionRow key={item.id} {...{ item, accessToken, canEdit, transcript, onUpdate }} />)}</tbody>
      </table>
    </div>
  </div>;
}

function ActionRow({ item, accessToken, canEdit, transcript, onUpdate }: {
  item: ActionItemOut; accessToken: string; canEdit: boolean; transcript?: string | null;
  onUpdate: (item: ActionItemOut) => void;
}) {
  const values = () => ({ task: item.task, owner: item.owner ?? "", deadline_iso: item.deadline_iso ?? "", confidence: item.confidence });
  const [draft, setDraft] = useState(values);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const inFlight = useRef(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const flags = concerns(item);
  const quote = item.source_quote?.trim();
  const position = quote && transcript ? transcript.toLowerCase().indexOf(quote.toLowerCase()) : -1;
  const context = position >= 0 && transcript && quote
    ? transcript.slice(Math.max(0, position - 180), Math.min(transcript.length, position + quote.length + 180)) : null;
  const cell = "border border-[#dde1e8] px-4 py-3 align-top break-words";
  const colours = { high: "bg-green-50 text-green-800", medium: "bg-amber-50 text-amber-800", low: "bg-red-50 text-red-800" };

  async function save() {
    if (inFlight.current || !canEdit) return;
    const nextErrors: Record<string, string> = {};
    const task = draft.task.trim();
    const owner = draft.owner.trim();
    if (!task) nextErrors.task = "Enter a task description.";
    if (item.owner?.trim() && !owner) nextErrors.owner = "Keep the assigned person or enter a replacement.";
    if (item.deadline_iso && !draft.deadline_iso) nextErrors.deadline_iso = "Keep the deadline or choose a replacement date.";
    if (draft.deadline_iso && (!/^\d{4}-\d{2}-\d{2}$/.test(draft.deadline_iso) ||
      Number.isNaN(Date.parse(draft.deadline_iso)) || new Date(draft.deadline_iso).toISOString().slice(0, 10) !== draft.deadline_iso))
      nextErrors.deadline_iso = "Enter a valid date.";
    if (!["high", "medium", "low"].includes(draft.confidence)) nextErrors.confidence = "Choose a confidence level.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    const edit: ActionItemEdit = {};
    if (task !== item.task) edit.task = task;
    if (owner !== (item.owner ?? "")) edit.owner = owner;
    if (draft.deadline_iso !== (item.deadline_iso ?? "")) edit.deadline_iso = draft.deadline_iso;
    if (draft.confidence !== item.confidence) edit.confidence = draft.confidence;
    if (!Object.keys(edit).length) { setEditing(false); return; }
    inFlight.current = true;
    setSaving(true);
    try {
      await editActionItem(item.id, edit, accessToken);
      onUpdate({ ...item, ...edit });
      setEditing(false);
      setSaved(true);
    } catch {
      setErrors({ save: "Could not save this action item. Your edits are kept. Try again." });
    } finally { inFlight.current = false; setSaving(false); }
  }

  return <>
    <tr className={editing ? "bg-blue-50" : "even:bg-gray-50"}>
      <td className={`${cell} w-[30%]`}>
        <p className="font-medium whitespace-pre-wrap">{item.task || "Missing task"}</p>
        {flags.length > 0 && <div className="mt-2 text-xs text-amber-900"><strong>Requires review</strong><ul className="mt-1 list-disc pl-4">{flags.map(flag => <li key={flag}>{flag}</li>)}</ul></div>}
        {canEdit && !editing && <button type="button" title="Edit" aria-label={`Edit action item: ${item.task}`} onClick={() => { setDraft(values()); setErrors({}); setSaved(false); setEditing(true); }} className="mt-3 rounded border px-3 py-1.5 text-xs font-semibold text-[#003366]">Edit</button>}
        {saved && <p role="status" className="mt-2 text-xs text-green-800">Action item saved.</p>}
        {editing && <p className="mt-2 text-xs font-semibold text-blue-900">Editing · changes are not saved</p>}
      </td>
      <td className={cell}>{item.owner?.trim() || "Missing owner"}</td>
      <td className={cell}>{item.deadline_iso || item.deadline_text?.trim() || "Missing deadline"}</td>
      <td className={cell}><span className={`rounded-full px-2 py-1 text-xs font-semibold ${colours[item.confidence]}`}>{item.confidence.charAt(0).toUpperCase() + item.confidence.slice(1)}</span></td>
      <td className={`${cell} w-[28%]`}>{quote ? <details>
        <summary className="cursor-pointer text-[#003366]">View source evidence</summary>
        <p className="mt-2 text-xs font-semibold">Extracted source quote</p>
        <blockquote className="mt-1 border-l-2 border-[#C9A52C] pl-3 whitespace-pre-wrap">{item.source_quote}</blockquote>
        {context ? <><p className="mt-3 text-xs font-semibold">Matching transcript context (first exact text match)</p><p className="mt-1 whitespace-pre-wrap text-xs">{context}</p></>
          : <p className="mt-2 text-xs text-gray-500">{transcript ? "No exact match in the current transcript. Check the transcript to verify this quote." : "Transcript unavailable for comparison."}</p>}
      </details> : <p className="text-gray-500">No source evidence provided.</p>}</td>
    </tr>
    {editing && <tr><td colSpan={5} className="border border-blue-200 bg-blue-50 p-4">
      <form aria-label={`Edit action item: ${item.task}`} noValidate onSubmit={event => { event.preventDefault(); void save(); }}>
        <fieldset disabled={saving || !canEdit} className="grid gap-3 sm:grid-cols-2">
          <legend className="mb-2 font-semibold">Edit action item</legend>
          {(["task", "owner", "deadline_iso", "confidence"] as const).map(field => {
            const id = `action-${item.id}-${field}`;
            const label = { task: "Task", owner: "Owner", deadline_iso: "Deadline", confidence: "Confidence" }[field];
            const props = { id, "aria-invalid": !!errors[field], "aria-describedby": errors[field] ? `${id}-error` : undefined, className: "mt-1 w-full rounded border border-gray-400 bg-white p-2" };
            return <div key={field}><label htmlFor={id} className="text-sm font-medium">{label}{field === "task" && " (required)"}</label>
              {field === "confidence" ? <select {...props} value={draft.confidence} onChange={e => setDraft({ ...draft, confidence: e.target.value as Confidence })}>{["high", "medium", "low"].map(value => <option key={value} value={value}>{value.charAt(0).toUpperCase() + value.slice(1)}</option>)}</select>
                : field === "task" ? <textarea {...props} autoFocus value={draft.task} onChange={e => setDraft({ ...draft, task: e.target.value })} />
                : <input {...props} type={field === "deadline_iso" ? "date" : "text"} value={draft[field]} onChange={e => setDraft({ ...draft, [field]: e.target.value })} />}
              {errors[field] && <p id={`${id}-error`} role="alert" className="mt-1 text-xs text-red-700">{errors[field]}</p>}
            </div>;
          })}
        </fieldset>
        <p className="mt-3 text-xs text-gray-600">Missing owner or deadline may remain unspecified. Existing values cannot be accidentally cleared. Spoken deadlines stay available as extracted evidence.</p>
        {item.deadline_text && <p className="mt-1 text-xs text-gray-600">Extracted deadline: {item.deadline_text}</p>}
        {errors.save && <p role="alert" className="mt-2 text-sm text-red-700">{errors.save}</p>}
        <div className="mt-3 flex gap-2">
          <button type="submit" disabled={saving || !canEdit} className="rounded bg-[#003366] px-3 py-2 text-sm text-white disabled:opacity-60">{saving ? "Saving…" : "Save changes"}</button>
          <button type="button" disabled={saving} onClick={() => { setEditing(false); setErrors({}); }} className="rounded border px-3 py-2 text-sm disabled:opacity-60">Cancel</button>
        </div>
      </form>
    </td></tr>}
  </>;
}
