import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import RecentMeetings from "../recent-meetings";
import * as api from "@/lib/api";
import type { MeetingOut, RecentMeeting, RecordingProcessingRequest } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  getRecentMeetings: vi.fn(), getProcessingRequests: vi.fn(), requestRecordingProcessing: vi.fn(),
  decideRecordingProcessing: vi.fn(), processRecentMeeting: vi.fn(),
}));

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  vi.mocked(api.getRecentMeetings).mockResolvedValue([]);
  vi.mocked(api.getProcessingRequests).mockResolvedValue([]);
});

it("restores cached meetings immediately after remount and revalidates in the background", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([event("view")]);
  const first = render(<RecentMeetings token="token" cacheIdentity="reviewer@example.test" isSubscribed />);
  expect(await screen.findByRole("link", { name: "View" })).toBeInTheDocument();
  first.unmount();

  vi.mocked(api.getRecentMeetings).mockReturnValue(new Promise(() => {}));
  render(<RecentMeetings token="token" cacheIdentity="reviewer@example.test" isSubscribed />);

  expect(screen.getByRole("link", { name: "View" })).toBeInTheDocument();
  expect(screen.queryByText(/Loading recent meetings/i)).not.toBeInTheDocument();
  expect(api.getRecentMeetings).toHaveBeenCalledTimes(2);
});

it("shows expired cached meetings while silently refreshing them", async () => {
  sessionStorage.setItem(
    "meeting-intel:recent-meetings:v1:reviewer%40example.test",
    JSON.stringify({ version: 1, cachedAt: Date.now() - 10 * 60 * 1000, events: [event("view")] }),
  );
  vi.mocked(api.getRecentMeetings).mockRejectedValue(new Error("calendar unavailable"));

  render(<RecentMeetings token="token" cacheIdentity="reviewer@example.test" isSubscribed />);

  expect(screen.getByRole("link", { name: "View" })).toBeInTheDocument();
  expect(screen.queryByText(/Loading recent meetings/i)).not.toBeInTheDocument();
  await waitFor(() => expect(api.getRecentMeetings).toHaveBeenCalledOnce());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("defaults to the last 7 days with recordings", () => {
  render(<RecentMeetings token="token" isSubscribed />);
  expect(screen.getByRole("combobox", { name: "Time" })).toHaveValue("7");
  expect(screen.getByRole("combobox", { name: "Recording" })).toHaveValue("with");
});

function event(action: RecentMeeting["action"]): RecentMeeting {
  return { event_id: action, subject: action, action, status: "ended", start: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    end: new Date(Date.now() - 23 * 60 * 60 * 1000).toISOString(), start_tz: "UTC", organizer_name: "Organizer", organizer_email: "org@example.test",
    attendees: [], attendee_count: 0, platform: "Teams", location: null, meeting_id: "meeting", processing_status: "pending" };
}

function request(can_decide = true): RecordingProcessingRequest {
  return { id: "request", event_id: "event", subject: "Owner approval", start: null, end: null,
    organizer_email: "org@example.test", requester_user_id: "requester", requester_name: "Requester",
    status: "pending", can_decide, created_at: "2026-09-03T10:00:00Z", decided_at: null, meeting_id: null };
}

it("renders all Recent actions and disables repeat actions for pending/queued", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([
    event("view"), event("process"), event("request_processing"), event("request_pending"),
    event("processing"), event("no_recording"), event("unavailable"),
  ]);
  render(<RecentMeetings token="token" isSubscribed />);
  fireEvent.change(screen.getByRole("combobox", { name: "Recording" }), { target: { value: "all" } });
  expect(await screen.findByRole("link", { name: "View" })).toHaveAttribute("href", "/meetings/meeting");
  expect(screen.getByRole("button", { name: "Process" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Request Processing" })).toBeEnabled();
  for (const text of ["Request Pending", "Processing: Queued", "Unavailable"])
    expect(screen.getByText(text)).toBeInTheDocument();
  expect(screen.getAllByText("No Recording").length).toBeGreaterThan(0);
  expect(screen.getAllByRole("button", { name: "Request Processing" })).toHaveLength(1);
});

it("merges historical meetings, removes stable-id duplicates, and reveals history on demand", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([{ ...event("view"), meeting_id: "same", subject: "Recent copy" }]);
  const historical = [historicalMeeting("same", "Duplicate"), historicalMeeting("older", "Older historical", "2025-01-02T10:00:00Z")];
  const requestAccess = vi.fn().mockResolvedValue(undefined);
  render(<RecentMeetings token="token" cacheIdentity="reviewer@example.test" isSubscribed historical={historical} onRequestHistoricalAccess={requestAccess} />);

  expect(await screen.findByText("Recent copy")).toBeInTheDocument();
  expect(screen.queryByText("Duplicate")).not.toBeInTheDocument();
  expect(screen.queryByText("Older historical")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Time" }), { target: { value: "all" } });
  expect(screen.getByText("Older historical")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Request Access" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Request Access" }));
  expect(screen.getByRole("button", { name: "View only" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "View and edit" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "View and edit" }));
  await waitFor(() => expect(requestAccess).toHaveBeenCalledWith("older", "edit"));
});

it("hides no-recording meetings by default and never offers a processing request for them", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([event("no_recording")]);
  render(<RecentMeetings token="token" isSubscribed />);
  await waitFor(() => expect(api.getRecentMeetings).toHaveBeenCalledOnce());
  expect(screen.queryByText("no_recording")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Recording" }), { target: { value: "without" } });
  expect(screen.getAllByText("No Recording").length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: "Request Processing" })).not.toBeInTheDocument();
});

function historicalMeeting(id: string, title: string, recordedAt = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString()): MeetingOut {
  return { id, title, recorded_at: recordedAt, state: "approved", summary: null, action_items: [], calendar_participants: [],
    organizer_upn: "owner@example.test", email_recipients: [], approved_recipients: [], is_organizer: false, can_edit: false,
    can_request_edit_access: false, edit_access_status: "none", edit_access_requests: [], speaker_candidates: [], speaker_mappings: {}, speaker_sample_labels: [] };
}

it("sends only the Calendar event reference and refreshes to pending", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValueOnce([event("request_processing")]).mockResolvedValue([event("request_pending")]);
  vi.mocked(api.requestRecordingProcessing).mockResolvedValue(request(false));
  render(<RecentMeetings token="token" isSubscribed />);
  fireEvent.click(await screen.findByRole("button", { name: "Request Processing" }));
  expect(await screen.findByText("Request Pending")).toBeInTheDocument();
  expect(api.requestRecordingProcessing).toHaveBeenCalledWith("request_processing", "token");
});

it.each([true, false])("owner can decide approved=%s", async (approved) => {
  vi.mocked(api.getProcessingRequests).mockResolvedValue([request()]);
  vi.mocked(api.decideRecordingProcessing).mockResolvedValue({ ...request(false), status: approved ? "approved" : "denied" });
  render(<RecentMeetings token="token" isSubscribed />);
  fireEvent.click(await screen.findByRole("button", { name: approved ? "Approve" : "Deny" }));
  await waitFor(() => expect(api.decideRecordingProcessing).toHaveBeenCalledWith("request", approved, "token"));
});

it("does not offer owner controls to requester", async () => {
  vi.mocked(api.getProcessingRequests).mockResolvedValue([request(false)]);
  render(<RecentMeetings token="token" isSubscribed />);
  await screen.findByText("Owner approval");
  expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
});

it("does not turn Graph failure into an empty calendar", async () => {
  vi.mocked(api.getRecentMeetings).mockRejectedValue(new Error("502"));
  render(<RecentMeetings token="token" isSubscribed />);
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
  expect(screen.queryByText("No recently ended meetings.")).not.toBeInTheDocument();
});

it("uses the server-verified own Process endpoint", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([event("process")]);
  vi.mocked(api.processRecentMeeting).mockResolvedValue({ ok: true });
  render(<RecentMeetings token="token" isSubscribed />);
  fireEvent.click(await screen.findByRole("button", { name: "Process" }));
  await waitFor(() => expect(api.processRecentMeeting).toHaveBeenCalledWith("process", "token"));
});

it("refreshes without clearing successful meetings or processing requests", async () => {
  vi.mocked(api.getRecentMeetings)
    .mockResolvedValueOnce([event("process")])
    .mockRejectedValueOnce(new Error("calendar unavailable"));
  vi.mocked(api.getProcessingRequests)
    .mockResolvedValueOnce([request(false)])
    .mockRejectedValueOnce(new Error("requests unavailable"));
  render(<RecentMeetings token="token" isSubscribed />);

  expect(await screen.findByRole("button", { name: "Process" })).toBeInTheDocument();
  expect(screen.getByText("Owner approval")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
  expect(screen.getByRole("button", { name: "Process" })).toBeInTheDocument();
  expect(screen.getByText("Owner approval")).toBeInTheDocument();
  expect(api.getRecentMeetings).toHaveBeenCalledTimes(2);
  expect(api.getProcessingRequests).toHaveBeenCalledTimes(2);
});
