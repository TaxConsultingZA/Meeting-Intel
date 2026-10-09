"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { ChevronLeft, CheckCircle2, Loader2, Pause, Play } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import StateBadge from "@/components/state-badge";
import RecordingJobs from "@/components/recording-jobs";
import LocalDateTime from "@/components/local-date-time";
import PipelineView from "./pipeline-view";
import ActionItemReview from "./action-item-review";
import {
  ApiError,
  getMeeting,
  approveMeeting,
  previewMeetingEmail,
  editMeetingTranscript,
  saveSpeakerMappings,
  requestMeetingEditAccess,
  decideMeetingEditAccess,
  getSpeakerSample,
  sendMeetingCopyToSelf,
} from "@/lib/api";
import type {
  MeetingOut,
  ActionItemOut,
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

type SpeakerCandidateValue = MeetingOut["speaker_candidates"][number];

function speakerCandidateUpn(candidate: SpeakerCandidateValue): string {
  return typeof candidate === "string" ? candidate : (candidate.upn || candidate.email);
}

function speakerCandidateLabel(candidate: SpeakerCandidateValue): string {
  if (typeof candidate === "string") return candidate;
  return candidate.display_name?.trim() || candidate.email || candidate.upn;
}

function mappingForLabel(mappings: Record<string, string | null>, label: string): string | null {
  const matching = Object.entries(mappings).find(([key]) => key.toLowerCase() === label.toLowerCase());
  return matching ? matching[1] : null;
}

function approvalStatusMessage(state: string, recipientCount: number): string {
  return state === "sent"
    ? `Meeting notes approved. Email submission accepted for ${recipientCount} selected recipient(s). Delivery to inboxes is not confirmed here. If the email does not arrive, ask an administrator to check mail delivery before resending.`
    : "Meeting notes approved. No email was submitted. No further approval action is needed.";
}

function approvalFailureMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Your session expired before approval could be confirmed. Sign in again and check the meeting status before trying again.";
    if (error.status === 403) return "You do not have permission to approve this meeting. Ask the meeting organiser or an administrator for help.";
    if (error.status === 409) return "Approval could not proceed with the current preview or meeting status. Refresh the meeting and review a fresh preview. If an earlier send is unconfirmed, ask an administrator to check before submitting again.";
    if (error.status === 422) return "The selected recipients could not be accepted. Refresh the meeting, check the recipient list, and review a fresh preview before approving.";
    if (error.status === 502) return "Email submission could not be confirmed, and approval is not confirmed. Ask an administrator to check the email audit and mail delivery before trying again; the email may already have been accepted.";
  }
  return "Approval could not be confirmed. Refresh the meeting status before trying again. If you already submitted an email, ask an administrator to check delivery before resending.";
}

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
  const [emailPreview, setEmailPreview] = useState<Awaited<ReturnType<typeof previewMeetingEmail>> | null>(null);
  const [previewingEmail, setPreviewingEmail] = useState(false);
  const [recipients, setRecipients] = useState<string[]>(initial.email_recipients ?? []);
  const previewMatchesRecipients = emailPreview !== null &&
    JSON.stringify([...new Set(recipients.map((value) => value.trim().toLowerCase()))].sort()) ===
    JSON.stringify(emailPreview.recipients);
  const [transcriptDraft, setTranscriptDraft] = useState(initial.transcript ?? "");
  const [editingTranscript, setEditingTranscript] = useState(false);
  const [speakerMappings, setSpeakerMappings] = useState<Record<string, string | null>>(initial.speaker_mappings ?? {});
  const [savingSpeakerMappings, setSavingSpeakerMappings] = useState(false);
  const [savingAccess, setSavingAccess] = useState(false);
  const [sendingSelfCopy, setSendingSelfCopy] = useState(false);
  const [pollingError, setPollingError] = useState<string | null>(null);
  const [approvalVerificationError, setApprovalVerificationError] = useState<string | null>(null);
  const [approvalFeedback, setApprovalFeedback] = useState<string | null>(null);
  const approvalInFlight = useRef(false);
  const previewInFlight = useRef(false);
  const cancelApprovalButton = useRef<HTMLButtonElement>(null);
  const pollingInFlight = useRef(false);

  const data = meeting.extracted_json ?? {};
  const isTranscriptOnly = data.extraction_mode === "transcript_only";
  const isReviewable = meeting.state === "awaiting_review";
  const isOrganizer = meeting.is_organizer ?? meeting.organizer_upn?.toLowerCase() === upn.toLowerCase();
  const canApprove = meeting.can_approve ?? isOrganizer;
  const canEdit = isReviewable && (meeting.can_edit || isOrganizer);
  const editAccessStatus = meeting.edit_access_status as string;
  const accessStatusMessage = isOrganizer || editAccessStatus === "organizer"
    ? "You are the meeting organiser and have full edit access."
    : editAccessStatus === "pending"
      ? "Edit access request pending. The meeting organiser will review it."
      : editAccessStatus === "approved"
        ? "Edit access approved."
        : editAccessStatus === "denied" || editAccessStatus === "rejected"
          ? "Edit access request denied."
          : null;
  const speakerLabels = Array.from(
    new Set(Array.from((meeting.transcript ?? "").matchAll(/\[(Speaker [^\]]+)\]/gi), (match) => match[1])),
  );
  const speakerMappingsChanged = speakerLabels.some(
    (label) => mappingForLabel(speakerMappings, label) !== mappingForLabel(meeting.speaker_mappings, label),
  );
  const reviewDrafts = useRef({ speakerMappingsChanged, editingTranscript });
  useEffect(() => {
    reviewDrafts.current = { speakerMappingsChanged, editingTranscript };
  }, [speakerMappingsChanged, editingTranscript]);
  const isProcessing = (["queued", "downloading", "transcribing", "extracting"] as ProcessingState[]).includes(meeting.state);
  const canSendSelfCopy = !isOrganizer
    && meeting.edit_access_status === "approved"
    && (meeting.state === "approved" || meeting.state === "sent");

  const refreshMeetingStatus = useCallback(async () => {
    if (document.visibilityState === "hidden" || pollingInFlight.current) return;
    pollingInFlight.current = true;
    await getMeeting(initial.id, accessToken)
      .then((next) => {
        setMeeting(next);
        if (!reviewDrafts.current.speakerMappingsChanged) setSpeakerMappings(next.speaker_mappings ?? {});
        if (!reviewDrafts.current.editingTranscript) setTranscriptDraft(next.transcript ?? "");
        setPollingError(null);
        setApprovalVerificationError(null);
      })
      .catch(() => {
        setPollingError("Unable to refresh meeting status. Please try again.");
      })
      .finally(() => { pollingInFlight.current = false; });
  }, [initial.id, accessToken]);

  useEffect(() => {
    if (!isProcessing) return;
    const timer = setInterval(refreshMeetingStatus, 10000);
    return () => clearInterval(timer);
  }, [isProcessing, refreshMeetingStatus]);

  async function handleApprove() {
    if (approvalInFlight.current || !emailPreview || !previewMatchesRecipients) return;
    approvalInFlight.current = true;
    setApproving(true);
    setApprovalFeedback(null);
    setApprovalVerificationError(null);
    try {
      const res = await approveMeeting(meeting.id, accessToken, recipients, emailPreview.fingerprint);
      let confirmedState = res.state;
      try {
        const latest = await getMeeting(meeting.id, accessToken);
        setMeeting(latest);
        setSpeakerMappings(latest.speaker_mappings ?? {});
        confirmedState = latest.state;
      } catch {
        // Keep the successful response state visible if reconciliation itself fails,
        // but make the unverifiable fields explicit to the user.
        setMeeting((m) => ({ ...m, state: res.state as never, approved_recipients: recipients }));
        setApprovalVerificationError("The latest approval status could not be verified. Refresh the status before taking another action. If email submission is unconfirmed, ask an administrator to check delivery before resending.");
      }
      setShowModal(false);
      toast.success(approvalStatusMessage(confirmedState, recipients.length));
    } catch (e: unknown) {
      setEmailPreview(null);
      try {
        const latest = await getMeeting(meeting.id, accessToken);
        setMeeting(latest);
        setSpeakerMappings(latest.speaker_mappings ?? {});
        if (latest.state === "approved" || latest.state === "sent") {
          setShowModal(false);
          toast.success(approvalStatusMessage(latest.state, latest.approved_recipients.length));
        } else {
          const message = approvalFailureMessage(e);
          setApprovalFeedback(message);
          toast.error(message);
        }
      } catch {
        setApprovalVerificationError("The latest approval status could not be verified. Refresh the status before taking another action. If email submission is unconfirmed, ask an administrator to check delivery before resending.");
        const message = "We could not confirm approval or load the latest meeting status. Refresh the status before trying again. Ask an administrator to check any email submission before resending.";
        setApprovalFeedback(message);
        toast.error(message);
      }
    } finally {
      approvalInFlight.current = false;
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
    if (previewInFlight.current || approvalInFlight.current) return;
    previewInFlight.current = true;
    setPreviewingEmail(true);
    try {
      const preview = await previewMeetingEmail(meeting.id, accessToken, recipients);
      setEmailPreview(preview);
      setApprovalFeedback(null);
      setShowEmailPreview(true);
    } catch {
      const message = "The email preview could not be prepared. No approval was submitted. Try preparing the preview again; if this continues, refresh the meeting or contact an administrator.";
      setApprovalFeedback(message);
      toast.error(message);
    } finally {
      previewInFlight.current = false;
      setPreviewingEmail(false);
    }
  }

  async function handleRequestEditAccess() {
    setSavingAccess(true);
    try {
      const result = await requestMeetingEditAccess(meeting.id, accessToken);
      setMeeting((current) => ({ ...current, edit_access_status: result.status as MeetingOut["edit_access_status"] }));
      toast.success("Edit request sent to the meeting organiser.");
    } catch (e) {
      toast.error(`Request failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingAccess(false);
    }
  }

  async function handleSendSelfCopy() {
    setSendingSelfCopy(true);
    try {
      const result = await sendMeetingCopyToSelf(meeting.id, upn, accessToken);
      toast.success(result.sent ? `A copy was sent to ${upn}.` : "Email delivery is disabled in this environment.");
    } catch (error) {
      toast.error(`Copy failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSendingSelfCopy(false);
    }
  }

  async function handleAccessDecision(requesterUpn: string, approved: boolean) {
    try {
      const request = meeting.edit_access_requests.find((item) => item.requester_upn === requesterUpn);
      await decideMeetingEditAccess(meeting.id, requesterUpn, approved, accessToken);
      setMeeting((current) => ({
        ...current,
        edit_access_requests: current.edit_access_requests.filter((request) => request.requester_upn !== requesterUpn),
      }));
      const label = request?.requested_access === "view" ? "View access" : "Edit access";
      toast.success(approved ? `${label} approved.` : `${label} declined.`);
    } catch (e) {
      toast.error(`Decision failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function handleSaveTranscript() {
    try {
      await editMeetingTranscript(meeting.id, transcriptDraft, accessToken);
      setMeeting((current) => ({ ...current, transcript: transcriptDraft }));
      setEditingTranscript(false);
      toast.success("Transcript saved.");
    } catch (e) {
      toast.error(`Save failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function handleSaveSpeakerMappings() {
    if (savingSpeakerMappings || !speakerMappingsChanged) return;
    setSavingSpeakerMappings(true);
    try {
      await saveSpeakerMappings(meeting.id, speakerMappings, accessToken);
      setMeeting((current) => ({ ...current, speaker_mappings: speakerMappings }));
      toast.success("Speaker names saved.");
    } catch (e) {
      toast.error(`Save failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingSpeakerMappings(false);
    }
  }

  return (
    <main className="max-w-6xl mx-auto px-6 py-7">
      <Link href="/" className="inline-flex items-center gap-1.5 text-[#6b7280] text-[13px] hover:text-[#003366] mb-4 transition-colors">
        <ChevronLeft size={15} /> Back to Dashboard
      </Link>

      {approvalVerificationError && (
        <div role="alert" className="mb-5 flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span>{approvalVerificationError}</span>
          <button
            type="button"
            onClick={() => {
              refreshMeetingStatus();
            }}
            className="shrink-0 rounded-md border border-amber-300 px-3 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100"
          >
            Retry refresh
          </button>
        </div>
      )}

      {pollingError && isProcessing && (
        <div role="alert" className="mb-5 flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span>{pollingError}</span>
          <button
            type="button"
            onClick={refreshMeetingStatus}
            className="shrink-0 rounded-md border border-amber-300 px-3 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100"
          >
            Retry refresh
          </button>
        </div>
      )}

      {meeting.state === "approved" || meeting.state === "sent" ? (
        <div role="status" aria-label="Meeting approval status" className="flex items-start gap-2.5 bg-green-50 border border-green-200 rounded-lg px-4 py-3 mb-5 text-green-800 text-[13.5px] font-medium">
          <CheckCircle2 size={16} className="text-green-600" />
          {approvalStatusMessage(meeting.state, meeting.approved_recipients.length)}
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-5 items-start">
        {/* Sidebar */}
        <aside aria-label="Meeting details and recording processing" className="min-w-0 space-y-4 lg:sticky lg:top-[76px]">
        <div className="bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
          <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-4 py-4">
            <h2 className="text-white text-[14px] font-semibold leading-snug">
              {meeting.title ?? "Untitled Meeting"}
            </h2>
          </div>
          <div className="px-4 py-4 flex flex-col gap-3">
            <div><span className="text-xs text-gray-500">Date</span><p className="text-sm"><LocalDateTime value={meeting.recorded_at ?? data.meeting_time} /></p></div>
            <MetaRow label="Platform"   value={data.platform ?? "Microsoft Teams"} />
            <MetaRow label="Organiser"  value={meeting.organizer_upn ?? "—"} />
            <MetaRow
              label="Attendees"
              value={meeting.calendar_participants.map((participant) => participant.name).join(", ") || "—"}
            />
            {(data.apologies?.length ?? 0) > 0 && (
              <MetaRow label="Apologies" value={data.apologies!.join(", ")} />
            )}
            <div className="h-px bg-[#dde1e8]" />
            <div>
              <span className="text-[11px] font-semibold text-[#6b7280] uppercase tracking-wide">Meeting status</span>
              <div className="mt-1"><StateBadge state={meeting.state} /></div>
            </div>
            <MetaRow label="Action Items" value={`${meeting.action_items.length} extracted`} />
            <div className="h-px bg-[#dde1e8]" />
            {accessStatusMessage && (
              <p className="rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-900" role="status">
                {accessStatusMessage}
              </p>
            )}
            {isReviewable && meeting.can_request_edit_access && !meeting.can_edit && (
              <button
                type="button"
                onClick={handleRequestEditAccess}
                disabled={savingAccess || meeting.edit_access_status === "pending"}
                className="w-full border border-[#C9A52C] text-[#003366] font-semibold py-2 rounded-md text-[12.5px] disabled:opacity-60"
              >
                {meeting.edit_access_status === "pending" ? "Edit request pending" : "Request edit access"}
              </button>
            )}
            {isOrganizer && meeting.edit_access_requests.length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
                <p className="mb-2 text-xs font-bold text-[#003366]">Access requests</p>
                {meeting.edit_access_requests.map((request) => (
                  <div key={request.requester_upn} className="mb-2 last:mb-0">
                    <p className="break-all text-xs text-[#374151]">{request.requester_upn}</p>
                    <p className="text-xs font-semibold text-[#003366]">{request.requested_access === "view" ? "View only" : "View and edit"}</p>
                    <div className="mt-1 flex gap-2">
                      <button onClick={() => handleAccessDecision(request.requester_upn, true)} className="text-xs font-semibold text-green-700">Approve</button>
                      <button onClick={() => handleAccessDecision(request.requester_upn, false)} className="text-xs font-semibold text-red-700">Decline</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {isReviewable && canApprove && (
              <button
                type="button"
                onClick={() => setShowModal(true)}
                className="w-full bg-[#C9A52C] hover:bg-[#e8c84a] text-[#003366] font-bold py-2.5 rounded-md text-[13.5px] transition-colors"
              >
                ✓ Approve Meeting Notes
              </button>
            )}
            {canSendSelfCopy && (
              <button
                type="button"
                onClick={handleSendSelfCopy}
                disabled={sendingSelfCopy}
                className="w-full rounded-md border border-[#C9A52C] bg-[#fffbea] py-2.5 text-[13px] font-bold text-[#003366] disabled:opacity-60"
              >
                {sendingSelfCopy ? "Sending…" : "Email a copy to myself"}
              </button>
            )}
            <button
              type="button"
              onClick={handlePreviewEmail}
              disabled={previewingEmail || approving || isProcessing}
              className="w-full border border-[#dde1e8] hover:border-[#003366] text-[#003366] font-semibold py-2 rounded-md text-[12.5px] transition-colors disabled:opacity-50"
            >
              {previewingEmail ? "Preparing preview…" : "Preview Email"}
            </button>
          </div>
        </div>
        <RecordingJobs
          token={accessToken}
          meetingId={meeting.id}
          onChanged={refreshMeetingStatus}
          onTerminalTransition={refreshMeetingStatus}
        />
        </aside>

        {/* Main content */}
        <div className="flex flex-col gap-4">
          {isProcessing ? (
            <PipelineView state={meeting.state} />
          ) : meeting.state === "cancelled" ? (
            <div className="rounded-lg border border-[#dde1e8] bg-white p-5"><h2 className="font-semibold text-[#003366]">Recording cancelled</h2><p className="mt-2 text-sm leading-6 text-[#6b7280]">Saved meeting information and transcript have been kept. Check the recording processing panel in the meeting sidebar for any recovery actions available to you.</p>{meeting.transcript && <pre className="mt-4 whitespace-pre-wrap rounded-md bg-[#fafbfc] p-4 text-sm leading-6">{meeting.transcript}</pre>}</div>
          ) : meeting.state === "failed" ? (
            <div className="bg-white rounded-lg border border-red-200 shadow-sm overflow-hidden">
              <div className="bg-red-600 border-b-[3px] border-[#C9A52C] px-5 py-4">
                <h2 className="text-white font-semibold text-[15px]">Processing Failed</h2>
                <p className="text-white/70 text-[13px] mt-0.5">This recording could not be processed.</p>
              </div>
              <div className="px-5 py-5">
                {meeting.error && (
                  <p className="text-[13.5px] text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3 font-medium">
                    Processing stopped before this attempt could finish. Check the recording processing panel in the meeting sidebar for available recovery actions.
                  </p>
                )}
                <p className="text-[13px] text-[#6b7280] mt-3">
                  Check the recording processing panel in the meeting sidebar for the latest status and any recovery actions available to you.
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
              hint={canEdit ? "Review evidence and edit action details" : "Read-only · existing edit access applies"}
            >
              <ActionItemReview
                items={meeting.action_items}
                accessToken={accessToken}
                transcript={meeting.transcript}
                canEdit={canEdit}
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

          {speakerLabels.length > 0 && (
            <Section title="Speaker Names" hint={canEdit ? "Match each detected voice to an Outlook attendee" : "Speaker names can be changed by approved editors"}>
              <div className="space-y-3.5">
                {speakerLabels.map((label) => (
                  <div key={label} className="grid items-center gap-2.5 rounded-md border border-[#edf0f4] bg-[#fafbfc] px-3 py-2.5 sm:grid-cols-[minmax(120px,180px)_120px_minmax(220px,1fr)]">
                    <span className="truncate text-[13px] font-semibold text-[#003366]" title={label}>{label}</span>
                    <div className="flex min-h-9 items-center">
                      {canApprove && (meeting.speaker_sample_labels ?? []).includes(label) && (
                      <SpeakerSampleButton
                        meetingId={meeting.id}
                        speakerLabel={label}
                        accessToken={accessToken}
                      />
                      )}
                    </div>
                    <select
                      aria-label={`Name for ${label}`}
                      disabled={!canEdit}
                      value={mappingForLabel(speakerMappings, label) ?? ""}
                      onChange={(event) => setSpeakerMappings((current) => ({ ...current, [label]: event.target.value || null }))}
                      className="h-9 min-w-0 rounded-md border border-[#cfd6df] bg-white px-3 text-sm text-[#1a1a2e] disabled:bg-[#f3f4f6] disabled:text-[#6b7280]"
                    >
                      <option value="">Unknown / Guest</option>
                      {meeting.speaker_candidates.map((candidate) => {
                        const value = speakerCandidateUpn(candidate);
                        return (
                          <option key={value} value={value}>
                            {speakerCandidateLabel(candidate)}
                          </option>
                        );
                      })}
                    </select>
                  </div>
                ))}
                {canEdit && <div className="flex justify-end pt-0.5">
                  <button
                    type="button"
                    onClick={handleSaveSpeakerMappings}
                    disabled={!speakerMappingsChanged || savingSpeakerMappings}
                    className="inline-flex h-9 items-center gap-1.5 rounded-md bg-[#003366] px-4 text-sm font-semibold text-white transition-colors hover:bg-[#0a4a8c] disabled:cursor-not-allowed disabled:bg-[#aeb9c5]"
                  >
                    {savingSpeakerMappings && <Loader2 size={14} className="animate-spin" />}
                    {savingSpeakerMappings ? "Saving…" : "Save speaker names"}
                  </button>
                </div>}
              </div>
            </Section>
          )}

          {meeting.transcript && (
            <Section title="Transcript">
              {editingTranscript ? (
                <div className="space-y-2">
                  <textarea value={transcriptDraft} onChange={(event) => setTranscriptDraft(event.target.value)} className="min-h-80 w-full rounded-md border border-[#dde1e8] p-4 text-[13px] leading-6" />
                  <div className="flex gap-2">
                    <button onClick={handleSaveTranscript} className="rounded-md bg-[#003366] px-4 py-2 text-sm font-semibold text-white">Save transcript</button>
                    <button onClick={() => { setTranscriptDraft(meeting.transcript ?? ""); setEditingTranscript(false); }} className="rounded-md border px-4 py-2 text-sm">Cancel</button>
                  </div>
                </div>
              ) : (
                <div className="relative max-h-96 overflow-y-auto rounded-md border border-[#dde1e8] bg-[#fafbfc] p-4">
                  {canEdit && <button onClick={() => setEditingTranscript(true)} className="absolute right-3 top-3 rounded border bg-white px-2 py-1 text-xs font-semibold text-[#003366]">Edit</button>}
                  <pre className="whitespace-pre-wrap pr-12 font-sans text-[13px] leading-6 text-[#374151]">{meeting.transcript}</pre>
                </div>
              )}
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
      {canApprove && <Dialog open={showModal} onOpenChange={(open) => { if (!approvalInFlight.current) setShowModal(open); }}>
        <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto" showCloseButton={!approving} initialFocus={cancelApprovalButton} aria-busy={approving}>
          <DialogHeader>
            <DialogTitle>Approve Meeting Notes</DialogTitle>
          </DialogHeader>
          <p className="text-[13.5px] text-[#1a1a2e] leading-6">
            Confirm you have reviewed <strong>{meeting.title ?? "Untitled meeting"}</strong>, then choose
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
                    disabled={approving || previewingEmail}
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
          <div className="rounded-md border border-blue-200 bg-blue-50/50 p-3 text-sm text-[#003366]">
            <p className="font-semibold">What approval does</p>
            <p className="mt-1 text-xs leading-5">Approval records these notes and action items as approved and ends this review. {recipients.length ? "It also requests an email to the selected recipients when email sending is enabled. Submitted email cannot be recalled from this screen." : "With no recipients selected, no email will be sent."}</p>
          </div>
          {previewMatchesRecipients && emailPreview && <div className="rounded-md border border-[#dde1e8] bg-[#fafbfc] p-3 text-xs text-[#374151]">
            <p className="font-semibold">Reviewed email subject</p>
            <p className="mt-1 break-words">{emailPreview.subject}</p>
            <p className="mt-2 font-semibold">Selected recipients ({emailPreview.recipients.length})</p>
            {emailPreview.recipients.length ? <ul className="mt-1 max-h-24 overflow-y-auto space-y-1">{emailPreview.recipients.map(email => <li key={email} className="break-all">{email}</li>)}</ul> : <p className="mt-1">None — approval only.</p>}
          </div>}
          {!previewMatchesRecipients && (
            <p className="text-xs text-[#6b7280]">Review an email preview for these recipients before approving. If you change recipients, review the preview again.</p>
          )}
          {approvalFeedback && <p role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">{approvalFeedback}</p>}
          {approving && <p role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-[#003366]"><Loader2 size={16} aria-hidden="true" className="animate-spin" />Submitting approval{recipients.length ? " and requesting email submission" : ""}… Keep this page open while we check the result.</p>}
          <DialogFooter>
            <button type="button" onClick={handlePreviewEmail} disabled={previewingEmail || approving}
              className="border border-[#dde1e8] text-[#003366] px-4 py-2 rounded-md text-sm font-semibold">
              {previewingEmail ? "Preparing preview…" : "Review Email Preview"}
            </button>
            <button
              type="button"
              ref={cancelApprovalButton}
              disabled={approving}
              onClick={() => setShowModal(false)}
              className="border border-[#dde1e8] text-[#003366] px-4 py-2 rounded-md text-sm font-semibold hover:border-[#003366] transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleApprove}
              disabled={approving || previewingEmail || !previewMatchesRecipients}
              className="inline-flex items-center justify-center gap-2 bg-[#C9A52C] hover:bg-[#e8c84a] text-[#003366] px-5 py-2 rounded-md text-sm font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#003366]"
            >
              {approving && <Loader2 size={16} aria-hidden="true" className="animate-spin" />}{approving ? "Submitting approval…" : recipients.length ? "Approve & Send Email" : "Approve Without Sending"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>}

      <Dialog open={showEmailPreview} onOpenChange={setShowEmailPreview}>
        <DialogContent className="sm:max-w-5xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Email Preview</DialogTitle>
            <p className="text-xs leading-5 text-[#6b7280]">Review the recipients, subject, and content below. This preview does not send email. Close it to return to the approval confirmation.</p>
          </DialogHeader>
          <div className="rounded-md border border-[#dde1e8] bg-[#fafbfc] px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-[#6b7280]">Meeting</p>
            <p className="mt-1 text-sm font-medium text-[#1a1a2e]">{meeting.title ?? "Untitled meeting"}</p>
            <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-[#6b7280]">Recipients ({emailPreview?.recipients.length ?? 0})</p>
            {emailPreview?.recipients.length ? <ul className="mt-1 max-h-28 overflow-y-auto space-y-1 text-sm text-[#374151]">{emailPreview.recipients.map(email => <li key={email} className="break-all">{email}</li>)}</ul> : <p className="mt-1 text-sm text-[#6b7280]">No recipients selected. Approval will not send email.</p>}
            <span className="mt-3 block text-xs font-semibold uppercase tracking-wide text-[#6b7280]">Subject</span>
            <p className="mt-1 text-sm font-medium text-[#1a1a2e]">{emailPreview?.subject}</p>
          </div>
          {emailPreview && (
            <iframe
              title="Meeting notes email preview"
              srcDoc={emailPreview.html}
              sandbox=""
              className="h-[45vh] min-h-48 w-full rounded-md border border-[#dde1e8] bg-white"
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

function SpeakerSampleButton({
  meetingId,
  speakerLabel,
  accessToken,
}: {
  meetingId: string;
  speakerLabel: string;
  accessToken: string;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const loadingRef = useRef(false);

  useEffect(() => () => {
    audioRef.current?.pause();
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  async function togglePlayback() {
    if (loadingRef.current) return;
    if (audioRef.current) {
      if (playing) {
        audioRef.current.pause();
        setPlaying(false);
      } else {
        await audioRef.current.play();
        setPlaying(true);
      }
      return;
    }

    loadingRef.current = true;
    setLoading(true);
    try {
      const blob = await getSpeakerSample(meetingId, speakerLabel, accessToken);
      const objectUrl = URL.createObjectURL(blob);
      const audio = new Audio(objectUrl);
      objectUrlRef.current = objectUrl;
      audioRef.current = audio;
      audio.addEventListener("ended", () => setPlaying(false));
      await audio.play();
      setPlaying(true);
    } catch (error) {
      toast.error(`Audio sample failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }

  return (
    <button
      type="button"
      onClick={togglePlayback}
      disabled={loading}
      aria-label={`${playing ? "Pause" : "Play"} audio sample for ${speakerLabel}`}
      className="inline-flex items-center gap-1.5 rounded-md border border-[#b8c7d9] bg-white px-2.5 py-2 text-xs font-semibold text-[#003366] hover:bg-[#f4f7fa] disabled:opacity-60"
    >
      {loading ? <Loader2 size={13} className="animate-spin" /> : playing ? <Pause size={13} /> : <Play size={13} />}
      {loading ? "Loading…" : playing ? "Playing" : "Play sample"}
    </button>
  );
}

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
