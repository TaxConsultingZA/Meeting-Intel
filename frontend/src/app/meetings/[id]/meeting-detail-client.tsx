"use client";
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { ChevronLeft, Pencil, Check, X, CheckCircle2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import StateBadge from "@/components/state-badge";
import PipelineView from "./pipeline-view";
import { editActionItem, approveMeeting, previewMeetingEmail } from "@/lib/api";
import type {
  MeetingOut,
  ActionItemOut,
  Confidence,
  ProcessingState,
  SpeakerHighlight,
} from "@/lib/types";

const SPEAKER_COLOURS = [
  "bg-[#003366]",
  "bg-[#1A5276]",
  "bg-[#154360]",
  "bg-[#0E3460]",
  "bg-[#1B2A4A]",
];

interface Props {
  meeting: MeetingOut;
  upn: string;
  accessToken: string;
}

export default function MeetingDetailClient({ meeting: initial, upn, accessToken }: Props) {
  const [meeting, setMeeting] = useState(initial);
  const [approving, setApproving] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [showEmailPreview, setShowEmailPreview] = useState(false);
  const [emailPreview, setEmailPreview] = useState<{ subject: string; html: string } | null>(null);
  const [previewingEmail, setPreviewingEmail] = useState(false);
  const [recipients, setRecipients] = useState<string[]>(initial.email_recipients ?? []);

  const data = meeting.extracted_json ?? {};
  const isTranscriptOnly = data.extraction_mode === "transcript_only";
  const isReviewable = meeting.state === "awaiting_review";
  const isOrganizer = meeting.organizer_upn?.toLowerCase() === upn.toLowerCase();
  const isProcessing = (["queued", "downloading", "transcribing", "extracting"] as ProcessingState[]).includes(meeting.state);

  async function handleApprove() {
    setApproving(true);
    try {
      const res = await approveMeeting(meeting.id, accessToken, recipients);
      setMeeting((m) => ({ ...m, state: res.state as never }));
      setShowModal(false);
      toast.success(
        res.state === "sent"
          ? `Meeting notes approved and emailed to ${recipients.length} selected recipient(s).`
          : "Meeting notes approved. No email was sent.",
      );
    } catch (e: unknown) {
      toast.error(`Approval failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setApproving(false);
    }
  }

  async function handleEditItem(updated: ActionItemOut) {
    setMeeting((m) => ({
      ...m,
      action_items: m.action_items.map((a) => (a.id === updated.id ? updated : a)),
    }));
  }

  async function handlePreviewEmail() {
    setPreviewingEmail(true);
    try {
      const preview = await previewMeetingEmail(meeting.id, accessToken);
      setEmailPreview(preview);
      setShowEmailPreview(true);
    } catch (e) {
      toast.error(`Preview failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPreviewingEmail(false);
    }
  }

  return (
    <main className="max-w-6xl mx-auto px-6 py-7">
      <Link href="/" className="inline-flex items-center gap-1.5 text-[#6b7280] text-[13px] hover:text-[#003366] mb-4 transition-colors">
        <ChevronLeft size={15} /> Back to Dashboard
      </Link>

      {meeting.state === "approved" || meeting.state === "sent" ? (
        <div className="flex items-center gap-2.5 bg-green-50 border border-green-200 rounded-lg px-4 py-3 mb-5 text-green-800 text-[13.5px] font-medium">
          <CheckCircle2 size={16} className="text-green-600" />
          {meeting.state === "sent"
            ? `Meeting notes approved and emailed to ${meeting.approved_recipients.length} selected recipient(s).`
            : "Meeting notes approved. No email was sent."}
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-5 items-start">
        {/* Sidebar */}
        <div className="lg:sticky lg:top-[76px] bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
          <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-4 py-4">
            <h2 className="text-white text-[14px] font-semibold leading-snug">
              {meeting.title ?? "Untitled Meeting"}
            </h2>
          </div>
          <div className="px-4 py-4 flex flex-col gap-3">
            <MetaRow label="Date"       value={data.meeting_time ?? "—"} />
            <MetaRow label="Platform"   value={data.platform ?? "Microsoft Teams"} />
            <MetaRow label="Organiser"  value={meeting.organizer_upn ?? "—"} />
            <MetaRow label="Attendees"  value={data.attendees?.join(", ") ?? "—"} />
            {(data.apologies?.length ?? 0) > 0 && (
              <MetaRow label="Apologies" value={data.apologies!.join(", ")} />
            )}
            <div className="h-px bg-[#dde1e8]" />
            <div>
              <span className="text-[11px] font-semibold text-[#6b7280] uppercase tracking-wide">Status</span>
              <div className="mt-1"><StateBadge state={meeting.state} /></div>
            </div>
            <MetaRow label="Action Items" value={`${meeting.action_items.length} extracted`} />
            <div className="h-px bg-[#dde1e8]" />
            {isReviewable && isOrganizer && (
              <button
                type="button"
                onClick={() => setShowModal(true)}
                className="w-full bg-[#C9A52C] hover:bg-[#e8c84a] text-[#003366] font-bold py-2.5 rounded-md text-[13.5px] transition-colors"
              >
                ✓ Approve Meeting Notes
              </button>
            )}
            <button
              type="button"
              onClick={handlePreviewEmail}
              disabled={previewingEmail || isProcessing}
              className="w-full border border-[#dde1e8] hover:border-[#003366] text-[#003366] font-semibold py-2 rounded-md text-[12.5px] transition-colors disabled:opacity-50"
            >
              {previewingEmail ? "Preparing preview…" : "Preview Email"}
            </button>
          </div>
        </div>

        {/* Main content */}
        <div className="flex flex-col gap-4">
          {isProcessing ? (
            <PipelineView state={meeting.state} />
          ) : meeting.state === "failed" ? (
            <div className="bg-white rounded-lg border border-red-200 shadow-sm overflow-hidden">
              <div className="bg-red-600 border-b-[3px] border-[#C9A52C] px-5 py-4">
                <h2 className="text-white font-semibold text-[15px]">Processing Failed</h2>
                <p className="text-white/70 text-[13px] mt-0.5">This recording could not be processed.</p>
              </div>
              <div className="px-5 py-5">
                {meeting.error && (
                  <p className="text-[13.5px] text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3 font-medium">
                    {meeting.error}
                  </p>
                )}
                <p className="text-[13px] text-[#6b7280] mt-3">
                  You can retry this recording from the <strong>Import Recordings</strong> panel on the dashboard.
                </p>
              </div>
            </div>
          ) : (
            <>
          {isTranscriptOnly && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 px-5 py-4 text-[13.5px] leading-6 text-blue-900">
              <strong>Transcript ready.</strong> Structured AI summaries and action-item
              extraction are currently disabled while the company selects an AI provider.
            </div>
          )}
          {data.objective && (
            <Section title="Meeting Objective">
              <p className="text-[13.5px] text-[#1a1a2e] leading-7">{data.objective}</p>
            </Section>
          )}

          {(data.speaker_highlights?.length ?? 0) > 0 && (
            <Section title="Speaker Highlights">
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                {data.speaker_highlights!.map((s, i) => (
                  <SpeakerCard key={i} highlight={s} colour={SPEAKER_COLOURS[i % SPEAKER_COLOURS.length]} />
                ))}
              </div>
            </Section>
          )}

          {(data.discussion_points?.length ?? 0) > 0 && (
            <Section title="Key Discussion Points">
              <DataTable
                headers={["Topic", "Discussion Summary", "Outcome / Decision"]}
                rows={data.discussion_points!.map((d) => [
                  <strong key="t">{d.topic}</strong>,
                  d.summary,
                  d.outcome ?? "—",
                ])}
              />
            </Section>
          )}

          {!isTranscriptOnly && (
            <Section
              title="Action Items"
              hint={isReviewable && isOrganizer ? "Hover a row to edit" : "Only the organiser can edit before approval"}
            >
              <ActionItemsTable
                items={meeting.action_items}
                upn={accessToken}
                canEdit={isReviewable && isOrganizer}
                onUpdate={handleEditItem}
              />
            </Section>
          )}

          {(data.deliverables?.length ?? 0) > 0 && (
            <Section title="Deliverables">
              <DataTable
                headers={["Deliverable", "Responsible", "Delivery Method", "Due Date"]}
                rows={data.deliverables!.map((d) => [
                  <strong key="d">{d.deliverable}</strong>,
                  d.responsible ?? "—",
                  d.delivery_method ?? "—",
                  d.due_date ?? "—",
                ])}
              />
            </Section>
          )}

          {(data.risks?.length ?? 0) > 0 && (
            <Section title="Risks / Challenges / Dependencies">
              <DataTable
                headers={["Item", "Impact", "Resolution", "Owner"]}
                rows={data.risks!.map((r) => [
                  <strong key="r">{r.item}</strong>,
                  r.impact ?? "—",
                  r.resolution ?? "—",
                  r.owner ?? "—",
                ])}
              />
            </Section>
          )}

          {(data.next_steps?.length ?? 0) > 0 && (
            <Section title="Next Steps">
              <ul className="flex flex-col gap-2">
                {data.next_steps!.map((s, i) => (
                  <li key={i} className="flex gap-2.5 text-[13.5px]">
                    <span className="text-[#C9A52C] font-bold text-base leading-snug shrink-0">•</span>
                    {s}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {meeting.transcript && (
            <Section title="Transcript">
              <div className="max-h-96 overflow-y-auto rounded-md border border-[#dde1e8] bg-[#fafbfc] p-4">
                <pre className="whitespace-pre-wrap font-sans text-[13px] leading-6 text-[#374151]">
                  {meeting.transcript}
                </pre>
              </div>
            </Section>
          )}

          {data.next_meeting && (
            <Section title="Next Meeting">
              <DataTable
                headers={[]}
                rows={[
                  [<strong key="date">Proposed Date</strong>, data.next_meeting.proposed_date ?? "—"],
                  [<strong key="time">Proposed Time</strong>, data.next_meeting.proposed_time ?? "—"],
                  [<strong key="agenda">Agenda Focus</strong>, data.next_meeting.agenda_focus ?? "—"],
                ]}
              />
            </Section>
          )}
            </>
          )}
        </div>
      </div>

      {/* Approve Modal */}
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve Meeting Notes</DialogTitle>
          </DialogHeader>
          <p className="text-[13.5px] text-[#1a1a2e] leading-6">
            Confirm you have reviewed <strong>{meeting.title}</strong>, then choose
            exactly who should receive the approved notes.
          </p>
          <div className="border border-[#dde1e8] rounded-md max-h-56 overflow-y-auto">
            {(meeting.email_recipients ?? []).length === 0 ? (
              <p className="p-3 text-sm text-[#6b7280]">No email addresses were found for this meeting.</p>
            ) : (
              meeting.email_recipients.map((email) => (
                <label
                  key={email}
                  className="flex items-center gap-3 px-3 py-2.5 border-b last:border-b-0 border-[#edf0f4] cursor-pointer hover:bg-[#fafbfc]"
                >
                  <input
                    type="checkbox"
                    checked={recipients.includes(email)}
                    onChange={(e) =>
                      setRecipients((current) =>
                        e.target.checked
                          ? [...current, email]
                          : current.filter((value) => value !== email),
                      )
                    }
                    className="h-4 w-4 accent-[#003366]"
                  />
                  <span className="text-sm text-[#1a1a2e]">{email}</span>
                  {email === meeting.organizer_upn?.toLowerCase() && (
                    <span className="ml-auto text-[11px] text-[#6b7280]">Organiser</span>
                  )}
                </label>
              ))
            )}
          </div>
          <p className="text-xs text-[#6b7280]">
            {recipients.length === 0
              ? "Approval will be recorded without sending an email."
              : `${recipients.length} recipient(s) selected.`}
          </p>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setShowModal(false)}
              className="border border-[#dde1e8] text-[#003366] px-4 py-2 rounded-md text-sm font-semibold hover:border-[#003366] transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleApprove}
              disabled={approving}
              className="bg-[#C9A52C] hover:bg-[#e8c84a] text-[#003366] px-5 py-2 rounded-md text-sm font-bold transition-colors disabled:opacity-60"
            >
              {approving ? "Approving…" : "✓ Confirm Approval"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showEmailPreview} onOpenChange={setShowEmailPreview}>
        <DialogContent className="max-w-5xl">
          <DialogHeader>
            <DialogTitle>Email Preview</DialogTitle>
          </DialogHeader>
          <div className="rounded-md border border-[#dde1e8] bg-[#fafbfc] px-4 py-3">
            <span className="text-xs font-semibold uppercase tracking-wide text-[#6b7280]">Subject</span>
            <p className="mt-1 text-sm font-medium text-[#1a1a2e]">{emailPreview?.subject}</p>
          </div>
          {emailPreview && (
            <iframe
              title="Meeting notes email preview"
              srcDoc={emailPreview.html}
              sandbox=""
              className="h-[60vh] w-full rounded-md border border-[#dde1e8] bg-white"
            />
          )}
          <DialogFooter>
            <button
              type="button"
              onClick={() => setShowEmailPreview(false)}
              className="border border-[#dde1e8] text-[#003366] px-4 py-2 rounded-md text-sm font-semibold hover:border-[#003366]"
            >
              Close Preview
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

/* ── Sub-components ── */

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-3.5 border-b border-[#dde1e8] bg-[#fafbfc]">
        <span className="w-1 h-5 bg-[#C9A52C] rounded-sm shrink-0" />
        <h3 className="text-[13.5px] font-bold text-[#003366]">{title}</h3>
        {hint && <span className="ml-auto text-[11.5px] text-[#6b7280]">{hint}</span>}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold text-[#6b7280] uppercase tracking-wide">{label}</div>
      <div className="text-[13px] font-medium text-[#1a1a2e] mt-0.5 break-all">{value}</div>
    </div>
  );
}

function SpeakerCard({ highlight: h, colour }: { highlight: SpeakerHighlight; colour: string }) {
  return (
    <div className="rounded-md overflow-hidden border border-[#dde1e8]">
      <div className={`px-3.5 py-2.5 border-b-2 border-[#C9A52C] ${colour}`}>
        <p className="text-white text-[13px] font-semibold">{h.speaker}</p>
        <p className="text-white/60 text-[11.5px] mt-0.5">{h.role ?? "Participant"}</p>
      </div>
      <div className="px-3.5 py-3 bg-[#fafbfc]">
        {h.key_points.length === 0 ? (
          <p className="text-[12px] text-[#9ca3af] italic">No key points captured</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {h.key_points.map((pt, i) => (
              <li key={i} className="flex gap-2 text-[12.5px] leading-snug">
                <span className="text-[#C9A52C] font-bold shrink-0">•</span>
                {pt}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function DataTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: React.ReactNode[][];
}) {
  return (
    <div className="overflow-x-auto -mx-5">
      <table className="w-full text-[13px] border-collapse">
        {headers.length > 0 && (
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th
                  key={i}
                  className="bg-[#003366] text-white text-[12px] font-semibold px-4 py-2.5 text-left border border-white/10"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 1 ? "bg-[#f8fafc]" : "bg-white"}>
              {row.map((cell, ci) => (
                <td key={ci} className="px-4 py-2.5 border border-[#dde1e8] align-top leading-relaxed">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ActionItemsTable({
  items,
  upn,
  canEdit,
  onUpdate,
}: {
  items: ActionItemOut[];
  upn: string;
  canEdit: boolean;
  onUpdate: (updated: ActionItemOut) => void;
}) {
  if (items.length === 0) {
    return <p className="text-[13px] text-[#9ca3af] italic">No action items extracted.</p>;
  }

  return (
    <div className="overflow-x-auto -mx-5">
      <table className="w-full text-[13px] border-collapse">
        <thead>
          <tr>
            {["Action", "Assigned To", "Due Date", "Confidence", "Source Quote"].map((h) => (
              <th key={h} className="bg-[#003366] text-white text-[12px] font-semibold px-4 py-2.5 text-left border border-white/10">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <EditableRow key={item.id} item={item} alt={i % 2 === 1} upn={upn} canEdit={canEdit} onUpdate={onUpdate} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EditableRow({
  item,
  alt,
  upn,
  canEdit,
  onUpdate,
}: {
  item: ActionItemOut;
  alt: boolean;
  upn: string;
  canEdit: boolean;
  onUpdate: (updated: ActionItemOut) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.task);
  const [saving, setSaving] = useState(false);
  const bg = alt ? "bg-[#f8fafc]" : "bg-white";

  async function save() {
    if (draft === item.task) { setEditing(false); return; }
    setSaving(true);
    try {
      await editActionItem(item.id, { task: draft }, upn);
      onUpdate({ ...item, task: draft });
      setEditing(false);
      toast.success("Action item updated.");
    } catch {
      toast.error("Failed to save — please try again.");
    } finally {
      setSaving(false);
    }
  }

  const confidenceColour: Record<Confidence, string> = {
    high:   "bg-green-50 text-green-800",
    medium: "bg-amber-50 text-amber-800",
    low:    "bg-red-50 text-red-800",
  };

  return (
    <tr className={`group ${bg} hover:bg-blue-50/40 transition-colors`}>
      <td className="px-4 py-2.5 border border-[#dde1e8] align-top w-[28%]">
        {editing ? (
          <div className="flex flex-col gap-1.5">
            <input
              autoFocus
              aria-label="Edit action item"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="w-full border-2 border-[#C9A52C] rounded px-2 py-1 text-[13px] bg-[#fffbea] outline-none"
            />
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="bg-[#C9A52C] text-[#003366] text-[12px] font-bold px-2.5 py-1 rounded flex items-center gap-1 disabled:opacity-60"
              >
                <Check size={11} /> {saving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={() => { setDraft(item.task); setEditing(false); }}
                className="bg-[#dde1e8] text-[#6b7280] text-[12px] px-2.5 py-1 rounded flex items-center gap-1"
              >
                <X size={11} /> Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-1.5">
            <span className="font-medium">{item.task}</span>
            {canEdit && (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-[#6b7280] hover:text-[#003366] mt-0.5 shrink-0"
                title="Edit"
              >
                <Pencil size={12} />
              </button>
            )}
          </div>
        )}
      </td>
      <td className="px-4 py-2.5 border border-[#dde1e8] align-top">{item.owner ?? "—"}</td>
      <td className="px-4 py-2.5 border border-[#dde1e8] align-top whitespace-nowrap">
        {item.deadline_text ?? item.deadline_iso ?? "—"}
      </td>
      <td className="px-4 py-2.5 border border-[#dde1e8] align-top">
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11.5px] font-semibold ${confidenceColour[item.confidence]}`}>
          {item.confidence.charAt(0).toUpperCase() + item.confidence.slice(1)}
        </span>
      </td>
      <td className="px-4 py-2.5 border border-[#dde1e8] align-top text-[#6b7280] italic">
        {item.source_quote ? `"${item.source_quote}"` : "—"}
      </td>
    </tr>
  );
}
