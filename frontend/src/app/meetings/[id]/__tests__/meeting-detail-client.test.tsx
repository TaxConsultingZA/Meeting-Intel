import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import MeetingDetailClient from "../meeting-detail-client";
import type { MeetingOut } from "@/lib/types";

import { toast } from "sonner";
import { ApiError, approveMeeting, getMeeting, previewMeetingEmail, saveSpeakerMappings } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, saveSpeakerMappings: vi.fn().mockResolvedValue(undefined),
    approveMeeting: vi.fn(), getMeeting: vi.fn(), previewMeetingEmail: vi.fn(), getRecordingJobs: vi.fn().mockResolvedValue([]) };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

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
  expect(await screen.findByRole("button", { name: "Approve & Send Email" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Review Email Preview" }));
  expect(await within(await screen.findByRole("dialog", { name: "Email Preview" })).findByText("Reviewed subject")).toBeInTheDocument();
  expect(previewMeetingEmail).toHaveBeenCalledWith("safe-meeting", "token", ["owner@example.com"]);
  fireEvent.click(screen.getByRole("button", { name: "Close Preview" }));
  const send = await screen.findByRole("button", { name: "Approve & Send Email" });
  expect(send).toBeEnabled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "Approve Without Sending" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Approve & Send Email" }));
  await waitFor(() => expect(approveMeeting).toHaveBeenCalledWith(
    "safe-meeting", "token", ["owner@example.com"], "reviewed-fingerprint"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Approve & Send Email" })).toBeDisabled());
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
  expect(screen.queryByText("Original spoken deadline")).not.toBeInTheDocument();
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
  const submit = screen.getByRole("button", { name: "Approve & Send Email" });
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
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("Delivery to inboxes is not confirmed");
});

it.each([
  [401, "Sign in again"], [403, "permission"], [409, "fresh preview"],
  [422, "recipient list"], [502, "email may already have been accepted"],
])("gives safe next steps for approval failure %s", async (status, guidance) => {
  vi.mocked(approveMeeting).mockRejectedValue(new ApiError(Number(status), "secret technical details"));
  vi.mocked(getMeeting).mockResolvedValue(approvalMeeting);
  const preview = await openReviewedApproval();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve & Send Email" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(String(guidance));
  expect(alert).not.toHaveTextContent("secret technical details");
  expect(screen.getByRole("button", { name: "Approve & Send Email" })).toBeDisabled();
});

it("records approval without claiming an email was sent when no recipients are selected", async () => {
  const meeting = { ...approvalMeeting, email_recipients: [] };
  vi.mocked(approveMeeting).mockResolvedValue({ ok: true, state: "approved" });
  vi.mocked(getMeeting).mockResolvedValue({ ...meeting, state: "approved" });
  const preview = await openReviewedApproval(meeting);
  expect(within(preview).getByText(/No recipients selected/)).toBeInTheDocument();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve Without Sending" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Approve Meeting Notes" })).not.toBeInTheDocument());
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("No email was submitted");
  expect(approveMeeting).toHaveBeenCalledWith("email-meeting", "token", [], "fingerprint");
});

it("does not encourage resending when approval and refresh both fail", async () => {
  vi.mocked(approveMeeting).mockRejectedValue(new Error("technical"));
  vi.mocked(getMeeting).mockRejectedValue(new Error("technical"));
  const preview = await openReviewedApproval();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve & Send Email" }));
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
  fireEvent.click(screen.getByRole("button", { name: "Approve & Send Email" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Approve Meeting Notes" })).not.toBeInTheDocument());
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("accepted for 1 selected recipient");
  expect(screen.getByRole("alert")).toHaveTextContent("before resending");
});

it("shows reconciled approval after a lost approval response without inviting a resend", async () => {
  vi.mocked(approveMeeting).mockRejectedValue(new Error("lost response"));
  vi.mocked(getMeeting).mockResolvedValue({ ...approvalMeeting, state: "sent", approved_recipients: ["owner@example.com"] });
  const preview = await openReviewedApproval();
  fireEvent.click(within(preview).getByRole("button", { name: "Close Preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve & Send Email" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Approve Meeting Notes" })).not.toBeInTheDocument());
  expect(screen.getByRole("status", { name: "Meeting approval status" })).toHaveTextContent("Email submission accepted");
  expect(toast.error).not.toHaveBeenCalled();
});

it("does not offer approval when the existing permission denies it", () => {
  render(<MeetingDetailClient meeting={{ ...approvalMeeting, is_organizer: false, can_approve: false, can_edit: false, edit_access_status: "none" }} upn="attendee@example.com" accessToken="token" />);
  expect(screen.queryByRole("button", { name: /Approve Meeting Notes/ })).not.toBeInTheDocument();
});
