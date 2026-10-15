import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import MeetingDetailClient from "../meeting-detail-client";
import type { MeetingOut } from "@/lib/types";

import { toast } from "sonner";
import { ApiError, approveMeeting, editActionItem, editMeetingTranscript, getMeeting, getRecordingJobs, previewMeetingEmail, saveSpeakerMappings } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, saveSpeakerMappings: vi.fn().mockResolvedValue(undefined),
    editActionItem: vi.fn().mockResolvedValue(undefined), editMeetingTranscript: vi.fn().mockResolvedValue(undefined),
    approveMeeting: vi.fn(), getMeeting: vi.fn(), previewMeetingEmail: vi.fn(), getRecordingJobs: vi.fn().mockResolvedValue([]) };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("shows safe extraction failure details with the existing sidebar recovery action", async () => {
  const meeting: MeetingOut = {
    id: "failed-meeting", title: "Failure", state: "failed", summary: null, transcript: "Saved transcript",
    action_items: [], extracted_json: {}, calendar_participants: [], organizer_upn: "owner@example.com",
    error: "SECRET stack, credentials, raw AI response", failure: { stage: "extraction", category: "invalid_output" },
    email_recipients: [], approved_recipients: [], is_organizer: true, can_edit: true,
    can_request_edit_access: false, edit_access_status: "organizer", edit_access_requests: [],
    speaker_candidates: [], speaker_mappings: {}, speaker_sample_labels: [],
  };
  vi.mocked(getRecordingJobs).mockResolvedValueOnce([{
    job_id: "failed-job", drive_item_id: "item", meeting_id: meeting.id, title: meeting.title,
    status: "failed", processing_status: "failed", review_status: null, phase: "failed",
    attempts: 1, max_attempts: 3, error: "SECRET", failure: meeting.failure,
    can_retry: true, can_cancel: false, can_reprocess: false, processing_enabled: true,
  }]);
  render(<MeetingDetailClient meeting={meeting} upn="owner@example.com" accessToken="token" />);
  expect(screen.getByRole("heading", { name: "AI extraction failed" })).toBeVisible();
  expect(screen.getByText(/Category: Unusable processing output/)).toBeVisible();
  expect(await screen.findByRole("button", { name: "Retry" })).toBeEnabled();
  expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Approve Meeting Notes/ })).not.toBeInTheDocument();
});

it("requires a matching recipient preview, sends its fingerprint, and clears it after rejection", async () => {
  const meeting: MeetingOut = {
    id: "safe-meeting", recorded_at: null, title: "Safety", state: "awaiting_review",
    summary: "Notes", transcript: null, action_items: [], extracted_json: {},
    calendar_participants: [], organizer_upn: "owner@example.com",
    email_recipients: ["owner@example.com"], approved_recipients: [],
    is_organizer: true, can_edit: true, can_approve: true, can_request_edit_access: false,
    edit_access_status: "organizer", edit_access_requests: [],
    speaker_candidates: [], speaker_mappings: {}, speaker_sample_labels: [],
  };
  vi.mocked(getMeeting).mockResolvedValue(meeting);
  vi.mocked(approveMeeting).mockRejectedValue(new Error("Review a fresh preview"));
  vi.mocked(previewMeetingEmail).mockResolvedValue({ subject: "Reviewed subject", html: "<p>Reviewed</p>",
    recipients: ["owner@example.com"], fingerprint: "reviewed-fingerprint" });
  render(<MeetingDetailClient meeting={meeting} upn="owner@example.com" accessToken="token" />);
  fireEvent.click(screen.getByRole("button", { name: /Approve Meeting Notes/ }));
  expect(await screen.findByRole("button", { name: "Approve Meeting Notes" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Review Email Preview" }));
  expect(await within(await screen.findByRole("dialog", { name: "Email Preview" })).findByText("Reviewed subject")).toBeInTheDocument();
  expect(previewMeetingEmail).toHaveBeenCalledWith("safe-meeting", "token", ["owner@example.com"]);
  fireEvent.click(screen.getByRole("button", { name: "Close Preview" }));
  expect(screen.getByText("Email submission")).toBeVisible();
  expect(screen.getByText(/Submission does not confirm delivery/)).toBeVisible();
  const send = await screen.findByRole("button", { name: "Approve Meeting Notes" });
  expect(send).toBeEnabled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "Approve Meeting Notes" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Approve Meeting Notes" }));
  await waitFor(() => expect(approveMeeting).toHaveBeenCalledWith(
    "safe-meeting", "token", ["owner@example.com"], "reviewed-fingerprint"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Approve Meeting Notes" })).toBeDisabled());
});

it("displays Calendar participants when extracted attendees are empty", () => {
  const meeting: MeetingOut = {
    id: "meeting-1",
    recorded_at: "2026-09-02T08:15:00Z",
    title: "test",
    state: "awaiting_review",
    summary: null,
    transcript: null,
    action_items: [],
    extracted_json: { attendees: [] },
    calendar_participants: [
      { name: "Sphesihle Mhlongo", email: "sphesihle@taxconsulting.co.za", is_organizer: false },
      { name: "Wei Jiuyang", email: "wei.jiuyang@taxconsulting.co.za", is_organizer: true },
    ],
    organizer_upn: "wei.jiuyang@taxconsulting.co.za",
    email_recipients: [],
    approved_recipients: [],
    is_organizer: true,
    can_edit: true,
    can_request_edit_access: false,
    edit_access_status: "organizer",
    edit_access_requests: [],
    speaker_candidates: [],
    speaker_mappings: {},
    speaker_sample_labels: [],
  };

  render(<MeetingDetailClient
    meeting={meeting}
    upn="wei.jiuyang@taxconsulting.co.za"
    accessToken="offline-test-token"
  />);

  expect(screen.getByText("Sphesihle Mhlongo, Wei Jiuyang")).toBeInTheDocument();
});

it("shows existing edit and final approval controls for an Admin projection", async () => {
  const meeting: MeetingOut = {
    id: "meeting-admin", recorded_at: null, title: "Private meeting", state: "awaiting_review",
    summary: "AI-generated notes", transcript: "[Speaker A] Existing transcript",
    action_items: [{ id: "action-1", task: "Follow up", owner: null, deadline_text: "Original spoken deadline",
      deadline_iso: "2026-07-15", confidence: "high", source_quote: null, approved: false }],
    extracted_json: { discussion_points: [{ topic: "Plan", summary: "Discussed", outcome: null }] },
    calendar_participants: [{ name: "Owner", email: "owner@taxconsulting.co.za", is_organizer: true }],
    organizer_upn: "owner@taxconsulting.co.za", email_recipients: ["owner@taxconsulting.co.za"],
    approved_recipients: [], is_organizer: false, can_edit: true, can_approve: true,
    can_request_edit_access: false, edit_access_status: "none", edit_access_requests: [],
    speaker_candidates: [{ upn: "owner@taxconsulting.co.za", email: "owner@taxconsulting.co.za", display_name: "Owner" }],
    speaker_mappings: {}, speaker_sample_labels: ["Speaker A"],
  };

  const view = render(<MeetingDetailClient meeting={meeting} upn="admin@taxconsulting.co.za" accessToken="token" />);

  expect(screen.getByText("Discussed")).toBeInTheDocument();
  expect(screen.getByText("2026-07-15")).toBeInTheDocument();
  expect(screen.getByText("Original wording: Original spoken deadline")).toBeInTheDocument();
  expect(screen.getByText("Existing transcript", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit action item: Follow up" })).toBeInTheDocument();
  expect(screen.getByLabelText("Name for Speaker A")).toBeEnabled();
  expect(screen.getByRole("option", { name: "Owner" })).toHaveValue("owner@taxconsulting.co.za");
  expect(screen.getByRole("button", { name: "Save speaker names" })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Name for Speaker A"), { target: { value: "owner@taxconsulting.co.za" } });
  fireEvent.click(screen.getByRole("button", { name: "Save speaker names" }));
  await waitFor(() => expect(saveSpeakerMappings).toHaveBeenCalledWith(
    "meeting-admin", { "Speaker A": "owner@taxconsulting.co.za" }, "token",
  ));

  view.rerender(<MeetingDetailClient
    meeting={{ ...meeting, speaker_mappings: { "Speaker A": "owner@taxconsulting.co.za" } }}
    upn="admin@taxconsulting.co.za"
    accessToken="token"
  />);
  expect(screen.getByLabelText("Name for Speaker A")).toHaveValue("owner@taxconsulting.co.za");
});

it("supports legacy string speaker candidates without object rendering", () => {
  const meeting: MeetingOut = {
    id: "meeting-legacy", recorded_at: null, title: "Legacy", state: "awaiting_review",
    summary: null, transcript: "[Speaker A] Existing transcript", action_items: [], extracted_json: null,
    calendar_participants: [], organizer_upn: "owner@taxconsulting.co.za", email_recipients: [], approved_recipients: [],
    is_organizer: true, can_edit: true, can_request_edit_access: false, edit_access_status: "organizer",
    edit_access_requests: [], speaker_candidates: ["owner@taxconsulting.co.za"], speaker_mappings: {}, speaker_sample_labels: [],
  };

  render(<MeetingDetailClient meeting={meeting} upn="owner@taxconsulting.co.za" accessToken="token" />);

  expect(screen.getByRole("option", { name: "owner@taxconsulting.co.za" })).toHaveValue("owner@taxconsulting.co.za");
  expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
});

it.each([
  ["pending", "Edit access request pending. The meeting organiser will review it."],
  ["approved", "Edit access approved."],
  ["denied", "Edit access request denied."],
  ["rejected", "Edit access request denied."],
] as const)("shows the %s edit-access status", (status, message) => {
  const meeting: MeetingOut = {
    id: `meeting-access-${status}`, recorded_at: null, title: "Access state", state: "awaiting_review",
    summary: null, transcript: null, action_items: [], extracted_json: null,
    calendar_participants: [], organizer_upn: "owner@taxconsulting.co.za", email_recipients: [], approved_recipients: [],
    is_organizer: false, can_edit: status === "approved", can_request_edit_access: status !== "approved",
    edit_access_status: status as MeetingOut["edit_access_status"], edit_access_requests: [],
    speaker_candidates: [], speaker_mappings: {}, speaker_sample_labels: [],
  };

  render(<MeetingDetailClient meeting={meeting} upn="attendee@taxconsulting.co.za" accessToken="token" />);

  expect(screen.getByRole("status")).toHaveTextContent(message);
});

it("shows the organiser edit-access status", () => {
  const meeting: MeetingOut = {
    id: "meeting-access-organizer", recorded_at: null, title: "Organizer access", state: "awaiting_review",
    summary: null, transcript: null, action_items: [], extracted_json: null,
    calendar_participants: [], organizer_upn: "owner@taxconsulting.co.za", email_recipients: [], approved_recipients: [],
    is_organizer: true, can_edit: true, can_request_edit_access: false, edit_access_status: "organizer",
    edit_access_requests: [], speaker_candidates: [], speaker_mappings: {}, speaker_sample_labels: [],
  };

  render(<MeetingDetailClient meeting={meeting} upn="owner@taxconsulting.co.za" accessToken="token" />);

  expect(screen.getByRole("status")).toHaveTextContent("You are the meeting organiser and have full edit access.");
});


const approvalMeeting: MeetingOut = {
  id: "email-meeting", title: "Enterprise review", state: "awaiting_review", summary: "Notes",
  action_items: [], calendar_participants: [], organizer_upn: "owner@example.com",
  email_recipients: ["owner@example.com"], approved_recipients: [], is_organizer: true,
  can_edit: true, can_approve: true, can_request_edit_access: false, edit_access_status: "organizer",
  edit_access_requests: [], speaker_candidates: [], speaker_mappings: {}, speaker_sample_labels: [],
};

it("shows the stored summary near the top without substituting objective data or interpreting HTML", () => {
  const summary = "Budget approved.\n<em>Follow up next week.</em>";
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, summary, extracted_json: { objective: "Separate objective" } }} upn="owner@example.com" accessToken="token" />);
  const summaryHeading = screen.getByRole("heading", { name: "Meeting Summary" });
  const objectiveHeading = screen.getByRole("heading", { name: "Meeting Objective" });
  expect(summaryHeading.compareDocumentPosition(objectiveHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const section = summaryHeading.parentElement!.parentElement!;
  expect(section).toHaveTextContent("Budget approved.");
  expect(section).toHaveTextContent("<em>Follow up next week.</em>");
  expect(section.querySelector("em")).toBeNull();
  expect(section).not.toHaveTextContent("Separate objective");
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeEnabled();
});

it.each([null, "", " \n "])("shows an honest empty state for summary %s", summary => {
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, summary, extracted_json: { objective: "Existing objective" } }} upn="owner@example.com" accessToken="token" />);
  expect(screen.getByRole("heading", { name: "Meeting Summary" })).toBeVisible();
  expect(screen.getByText("No meeting summary is available.")).toBeVisible();
  expect(screen.getByText("Existing objective")).toBeVisible();
});

it.each(["queued", "failed", "cancelled"] as const)("preserves the %s screen without presenting incomplete results", state => {
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, state }} upn="owner@example.com" accessToken="token" />);
  expect(screen.queryByRole("heading", { name: "Meeting Summary" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Approve Meeting Notes/ })).not.toBeInTheDocument();
});

const reviewAction = { id: "a1", task: "Send report", owner: "Alex", deadline_iso: null,
  deadline_text: null, confidence: "high" as const, source_quote: "Send report", approved: false };

it("keeps approval blocked until every action editor has been saved or cancelled", async () => {
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, action_items: [reviewAction, { ...reviewAction, id: "a2", task: "Book review" }] }} upn="owner@example.com" accessToken="token" />);
  const approve = screen.getByRole("button", { name: /Approve Meeting Notes/ });
  fireEvent.click(screen.getByRole("button", { name: "Edit action item: Send report" }));
  fireEvent.click(screen.getByRole("button", { name: "Edit action item: Book review" }));
  expect(approve).toBeDisabled();
  expect(screen.getByRole("button", { name: "Preview Email" })).toBeDisabled();
  expect(screen.getByText(/Save or discard your changes/)).toBeVisible();
  fireEvent.click(within(screen.getByRole("form", { name: "Edit action item: Send report" })).getByRole("button", { name: "Cancel" }));
  expect(approve).toBeDisabled();
  const remaining = screen.getByRole("form", { name: "Edit action item: Book review" });
  fireEvent.change(within(remaining).getByLabelText("Task (required)"), { target: { value: "Book final review" } });
  fireEvent.click(within(remaining).getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(approve).toBeEnabled());
  expect(approveMeeting).not.toHaveBeenCalled();
});

it("blocks approval during action saves and preserves the block on save failure", async () => {
  let fail!: (error: Error) => void;
  vi.mocked(editActionItem).mockReturnValueOnce(new Promise((_, reject) => { fail = reject; }));
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, action_items: [reviewAction] }} upn="owner@example.com" accessToken="token" />);
  fireEvent.click(screen.getByRole("button", { name: "Edit action item: Send report" }));
  fireEvent.change(screen.getByLabelText("Task (required)"), { target: { value: "Send final report" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeDisabled();
  fail(new Error("Offline"));
  expect(await screen.findByText(/Your edits are kept/)).toBeVisible();
  expect(screen.getByLabelText("Task (required)")).toHaveValue("Send final report");
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeEnabled();
});

it("blocks transcript drafts and pending saves, retaining failed drafts for retry", async () => {
  let fail!: (error: Error) => void;
  vi.mocked(editMeetingTranscript).mockReturnValueOnce(new Promise((_, reject) => { fail = reject; }));
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, transcript: "Original transcript" }} upn="owner@example.com" accessToken="token" />);
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  const approve = screen.getByRole("button", { name: /Approve Meeting Notes/ });
  expect(approve).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Meeting transcript"), { target: { value: "Reviewed transcript" } });
  fireEvent.click(screen.getByRole("button", { name: "Save transcript" }));
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByLabelText("Meeting transcript")).toBeDisabled();
  expect(approve).toBeDisabled();
  fail(new Error("Offline"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save transcript" })).toBeEnabled());
  expect(screen.getByLabelText("Meeting transcript")).toHaveValue("Reviewed transcript");
  expect(approve).toBeDisabled();
  vi.mocked(editMeetingTranscript).mockResolvedValueOnce(undefined);
  fireEvent.click(screen.getByRole("button", { name: "Save transcript" }));
  await waitFor(() => expect(approve).toBeEnabled());
  expect(screen.queryByLabelText("Meeting transcript")).not.toBeInTheDocument();
  expect(editMeetingTranscript).toHaveBeenLastCalledWith(approvalMeeting.id, "Reviewed transcript", "token");
});

it("allows cancelling a transcript draft without saving it", () => {
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, transcript: "Original transcript" }} upn="owner@example.com" accessToken="token" />);
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Meeting transcript"), { target: { value: "Unsaved" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeEnabled();
  expect(screen.getByText("Original transcript")).toBeVisible();
  expect(editMeetingTranscript).not.toHaveBeenCalled();
});

it("blocks unsaved speaker names, pending saves, and failed saves", async () => {
  let fail!: (error: Error) => void;
  vi.mocked(saveSpeakerMappings).mockReturnValueOnce(new Promise((_, reject) => { fail = reject; }));
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, transcript: "[Speaker A] Hello",
    speaker_candidates: [{ upn: "owner@example.com", email: "owner@example.com", display_name: "Owner" }] }} upn="owner@example.com" accessToken="token" />);
  const speaker = screen.getByLabelText("Name for Speaker A");
  const approve = screen.getByRole("button", { name: /Approve Meeting Notes/ });
  fireEvent.change(speaker, { target: { value: "owner@example.com" } });
  expect(approve).toBeDisabled();
  expect(screen.getByRole("button", { name: "Preview Email" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Save speaker names" }));
  expect(speaker).toBeDisabled();
  expect(approve).toBeDisabled();
  fail(new Error("Offline"));
  await waitFor(() => expect(speaker).toBeEnabled());
  expect(speaker).toHaveValue("owner@example.com");
  expect(approve).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Save speaker names" }));
  await waitFor(() => expect(approve).toBeEnabled());
});

it.each(["action", "transcript", "speaker"])("requires a fresh preview after %s edits even if discarded", async kind => {
  await openReviewedApproval({ ...approvalMeeting, action_items: [reviewAction], transcript: "[Speaker A] Hello",
    speaker_candidates: [{ upn: "owner@example.com", email: "owner@example.com", display_name: "Owner" }] });
  fireEvent.click(screen.getByRole("button", { name: "Close Preview" }));
  fireEvent.click(within(screen.getByRole("dialog", { name: "Approve Meeting Notes" })).getByRole("button", { name: "Cancel" }));
  if (kind === "action") {
    fireEvent.click(screen.getByRole("button", { name: "Edit action item: Send report" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  } else if (kind === "transcript") {
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  } else {
    fireEvent.change(screen.getByLabelText("Name for Speaker A"), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText("Name for Speaker A"), { target: { value: "" } });
  }
  fireEvent.click(screen.getByRole("button", { name: /Approve Meeting Notes/ }));
  expect(screen.getByRole("button", { name: "Approve Meeting Notes" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Review Email Preview" }));
  await screen.findByRole("dialog", { name: "Email Preview" });
  fireEvent.click(screen.getByRole("button", { name: "Close Preview" }));
  expect(screen.getByRole("button", { name: "Approve Meeting Notes" })).toBeEnabled();
});

it.each(["approved", "sent"] as const)("keeps %s messaging consistent even when edit permission is present", state => {
  const meeting: MeetingOut = { ...approvalMeeting, state, transcript: "[Speaker A] Follow up",
    action_items: [{ id: "flagged", task: "Follow up", owner: null, deadline_iso: null,
      deadline_text: "Friday", confidence: "low", source_quote: "Follow up", approved: true }] };
  render(<MeetingDetailClient meeting={meeting} upn="owner@example.com" accessToken="token" />);
  expect(screen.getByText("Meeting notes are approved. Editing is locked after approval.")).toBeVisible();
  expect(screen.getByText("Approved with review flags")).toBeVisible();
  expect(screen.queryByText("Requires review")).not.toBeInTheDocument();
  expect(screen.queryByText(/full edit access/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Speaker names can be changed/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Approve Meeting Notes|Edit action item:/ })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Name for Speaker A")).toBeDisabled();
});

it("keeps editing and approval available while awaiting review", () => {
  render(<MeetingDetailClient meeting={{ ...approvalMeeting,
    action_items: [{ id: "flagged", task: "Follow up", owner: null, deadline_iso: null,
      deadline_text: null, confidence: "low", source_quote: null, approved: false }] }}
    upn="owner@example.com" accessToken="token" />);
  expect(screen.getByText("Requires review")).toBeVisible();
  expect(screen.getByRole("button", { name: "Edit action item: Follow up" })).toBeEnabled();
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeEnabled();
  expect(screen.queryByText("Approved with review flags")).not.toBeInTheDocument();
  expect(screen.queryByText(/Editing is locked/)).not.toBeInTheDocument();
});

async function openReviewedApproval(meeting = approvalMeeting) {
  vi.mocked(previewMeetingEmail).mockResolvedValue({ subject: "Final notes", html: "<p>Exact email content</p>", recipients: meeting.email_recipients, fingerprint: "fingerprint" });
  render(<MeetingDetailClient meeting={meeting} upn="owner@example.com" accessToken="token" />);
  fireEvent.click(screen.getByRole("button", { name: /Approve Meeting Notes/ }));
  await screen.findByRole("dialog", { name: "Approve Meeting Notes" });
  fireEvent.click(screen.getByRole("button", { name: "Review Email Preview" }));
  const preview = await screen.findByRole("dialog", { name: "Email Preview" });
  return preview;
}

it("identifies the meeting, exact recipients and email content before approval", async () => {
  const preview = await openReviewedApproval();
  expect(within(preview).getByText("Enterprise review")).toBeInTheDocument();
  expect(within(preview).getByText("owner@example.com")).toBeInTheDocument();
  expect(within(preview).getByText("Final notes")).toBeInTheDocument();
  expect(within(preview).getByTitle("Meeting notes email preview")).toHaveAttribute("srcdoc", "<p>Exact email content</p>");
  expect(within(preview).getByTitle("Meeting notes email preview")).toHaveAttribute("sandbox", "");
  expect(within(preview).getByText(/This preview does not send email/)).toBeInTheDocument();
  expect(approveMeeting).not.toHaveBeenCalled();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  expect(screen.getByText(/Submitted email cannot be recalled/)).toBeInTheDocument();
  expect(screen.getByText("Reviewed email subject")).toBeInTheDocument();
});

it("prevents duplicate approval and freezes confirmation while submitting", async () => {
  let resolve!: (value: { ok: boolean; state: string }) => void;
  vi.mocked(approveMeeting).mockReturnValue(new Promise(done => { resolve = done; }));
  vi.mocked(getMeeting).mockResolvedValue({ ...approvalMeeting, state: "sent", approved_recipients: ["owner@example.com"] });
  const preview = await openReviewedApproval();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  const submit = screen.getByRole("button", { name: "Approve Meeting Notes" });
  fireEvent.click(submit);
  fireEvent.click(submit);
  expect(approveMeeting).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Submitting approval…" })).toBeDisabled();
  expect(screen.getByRole("checkbox")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Review Email Preview" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("Keep this page open");
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(screen.getByRole("dialog", { name: "Approve Meeting Notes" })).toBeInTheDocument();
  resolve({ ok: true, state: "sent" });
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Approve Meeting Notes" })).not.toBeInTheDocument());
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("Email submission accepted");
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("Delivery confirmation is not available");
});

it.each([
  [401, "Sign in again"], [403, "permission"], [409, "fresh preview"],
  [422, "recipient list"], [502, "email may already have been accepted"],
])("gives safe next steps for approval failure %s", async (status, guidance) => {
  vi.mocked(approveMeeting).mockRejectedValue(new ApiError(Number(status), "secret technical details"));
  vi.mocked(getMeeting).mockResolvedValue(approvalMeeting);
  const preview = await openReviewedApproval();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve Meeting Notes" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(String(guidance));
  expect(alert).not.toHaveTextContent("secret technical details");
  expect(screen.getByRole("button", { name: "Approve Meeting Notes" })).toBeDisabled();
});

it("records approval without claiming an email was sent when no recipients are selected", async () => {
  const meeting = { ...approvalMeeting, email_recipients: [] };
  vi.mocked(approveMeeting).mockResolvedValue({ ok: true, state: "approved" });
  vi.mocked(getMeeting).mockResolvedValue({ ...meeting, state: "approved" });
  const preview = await openReviewedApproval(meeting);
  expect(within(preview).getByText(/No recipients selected/)).toBeInTheDocument();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve Meeting Notes" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Approve Meeting Notes" })).not.toBeInTheDocument());
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("No email was submitted");
  expect(approveMeeting).toHaveBeenCalledWith("email-meeting", "token", [], "fingerprint");
});

it("does not encourage resending when approval and refresh both fail", async () => {
  vi.mocked(approveMeeting).mockRejectedValue(new Error("technical"));
  vi.mocked(getMeeting).mockRejectedValue(new Error("technical"));
  const preview = await openReviewedApproval();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve Meeting Notes" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("check any email submission before resending")));
});

it("explains a preview failure without exposing provider details", async () => {
  vi.mocked(previewMeetingEmail).mockRejectedValue(new Error("Graph token secret"));
  render(<MeetingDetailClient meeting={approvalMeeting} upn="owner@example.com" accessToken="token" />);
  fireEvent.click(screen.getByRole("button", { name: /Approve Meeting Notes/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Review Email Preview" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("No approval was submitted");
  expect(screen.getByRole("alert")).not.toHaveTextContent("Graph token secret");
  expect(approveMeeting).not.toHaveBeenCalled();
});


it("reports accepted submission accurately if the status refresh fails", async () => {
  vi.mocked(approveMeeting).mockResolvedValue({ ok: true, state: "sent" });
  vi.mocked(getMeeting).mockRejectedValue(new Error("network"));
  const preview = await openReviewedApproval();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve Meeting Notes" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Approve Meeting Notes" })).not.toBeInTheDocument());
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("accepted for 1 selected recipient");
  expect(screen.getByRole("alert")).toHaveTextContent("before resending");
});

it("shows reconciled approval after a lost approval response without inviting a resend", async () => {
  vi.mocked(approveMeeting).mockRejectedValue(new Error("lost response"));
  vi.mocked(getMeeting).mockResolvedValue({ ...approvalMeeting, state: "sent", approved_recipients: ["owner@example.com"] });
  const preview = await openReviewedApproval();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve Meeting Notes" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Approve Meeting Notes" })).not.toBeInTheDocument());
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("Email submission accepted");
  expect(toast.error).not.toHaveBeenCalled();
});

it("does not offer approval when the existing permission denies it", () => {
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, is_organizer: false, can_approve: false, can_edit: false, edit_access_status: "none" }} upn="attendee@example.com" accessToken="token" />);
  expect(screen.queryByRole("button", { name: /Approve Meeting Notes/ })).not.toBeInTheDocument();
});
