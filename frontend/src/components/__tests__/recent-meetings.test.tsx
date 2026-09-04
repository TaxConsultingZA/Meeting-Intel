import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import RecentMeetings from "../recent-meetings";
import * as api from "@/lib/api";
import type { RecentMeeting, RecordingProcessingRequest } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  getRecentMeetings: vi.fn(), getProcessingRequests: vi.fn(), requestRecordingProcessing: vi.fn(),
  decideRecordingProcessing: vi.fn(), processRecentMeeting: vi.fn(),
}));

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getRecentMeetings).mockResolvedValue([]);
  vi.mocked(api.getProcessingRequests).mockResolvedValue([]);
});

function event(action: RecentMeeting["action"]): RecentMeeting {
  return { event_id: action, subject: action, action, status: "ended", start: "2026-09-03T10:00:00Z",
    end: "2026-09-03T11:00:00Z", start_tz: "UTC", organizer_name: "Organizer", organizer_email: "org@example.test",
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
  expect(await screen.findByRole("link", { name: "View" })).toHaveAttribute("href", "/meetings/meeting");
  expect(screen.getByRole("button", { name: "Process" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Request Processing" })).toBeEnabled();
  for (const text of ["Request Pending", "Processing: Queued", "No recording found", "Unavailable"])
    expect(screen.getByText(text)).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Request Processing" })).toHaveLength(1);
});

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
