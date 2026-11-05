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
    "meeting-intel:recent-meetings:v4:reviewer%40example.test",
    JSON.stringify({ version: 4, cachedAt: Date.now() - 10 * 60 * 1000, events: [event("view")] }),
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

it("searches loaded meeting titles, summaries, and participant names case-insensitively", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([
    { ...event("view"), event_id: "recent-title", subject: "Quarterly Budget" },
    { ...event("view"), event_id: "recent-person", meeting_id: "planning", subject: "Planning", attendees: ["Sam Example"] },
  ]);
  const historical = [
    { ...historicalMeeting("summary", "Old notes"), summary: "Launch readiness review" },
    { ...historicalMeeting("participant", "Old meeting"), calendar_participants: [{ name: "Taylor Example", email: "taylor@example.test", is_organizer: false }] },
  ];
  render(<RecentMeetings token="token" cacheIdentity="reviewer@example.test" isSubscribed historical={historical} />);
  await screen.findByText("Quarterly Budget");
  fireEvent.change(screen.getByRole("searchbox", { name: "Search meetings" }), { target: { value: "QUARTERLY" } });
  expect(screen.getByText("Quarterly Budget")).toBeInTheDocument();
  expect(screen.queryByText("Planning")).not.toBeInTheDocument();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search meetings" }), { target: { value: "LAUNCH READINESS" } });
  expect(screen.getByText("Old notes")).toBeInTheDocument();
  expect(screen.queryByText("Quarterly Budget")).not.toBeInTheDocument();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search meetings" }), { target: { value: "taylor example" } });
  expect(screen.getByText("Old meeting")).toBeInTheDocument();
  expect(screen.queryByText("Old notes")).not.toBeInTheDocument();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search meetings" }), { target: { value: "sam example" } });
  expect(screen.getByText("Planning")).toBeInTheDocument();
  expect(screen.queryByText("Old meeting")).not.toBeInTheDocument();
});

it("shows no-result feedback, clears search, and searches only loaded authorized data", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([{ ...event("view"), subject: "Accessible meeting" }]);
  render(<RecentMeetings token="token" isSubscribed />);
  await screen.findByText("Accessible meeting");
  const search = screen.getByRole("searchbox", { name: "Search meetings" });
  fireEvent.change(search, { target: { value: "not loaded or accessible" } });
  expect(screen.getByText("No meetings match this search and the selected filters.")).toBeInTheDocument();
  expect(api.getRecentMeetings).toHaveBeenCalledOnce();
  expect(screen.queryByText("An inaccessible meeting")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
  expect(screen.getByText("Accessible meeting")).toBeInTheDocument();
  expect(search).toHaveValue("");
  expect(api.getRecentMeetings).toHaveBeenCalledOnce();
});

it("revalidates after calendar sync without resetting the selected filters", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValueOnce([event("view")]);
  const view = render(<RecentMeetings token="token" isSubscribed refreshKey={0} />);
  expect(await screen.findByRole("link", { name: "View" })).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Time" }), { target: { value: "all" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Recording" }), { target: { value: "all" } });
  vi.mocked(api.getRecentMeetings).mockResolvedValueOnce([{ ...event("view"), subject: "Synced calendar row" }]);
  view.rerender(<RecentMeetings token="token" isSubscribed refreshKey={1} />);
  expect(await screen.findByText("Synced calendar row")).toBeVisible();
  expect(screen.getByRole("combobox", { name: "Time" })).toHaveValue("all");
  expect(screen.getByRole("combobox", { name: "Recording" })).toHaveValue("all");
  expect(api.getRecentMeetings).toHaveBeenCalledTimes(2);
});

function event(action: RecentMeeting["action"]): RecentMeeting {
  return { event_id: action, subject: action, action, status: "ended", start: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    end: new Date(Date.now() - 23 * 60 * 60 * 1000).toISOString(), start_tz: "UTC", organizer_name: "Organizer", organizer_email: "org@example.test",
    attendees: [], attendee_count: 0, platform: "Teams", location: null, meeting_id: action === "view" ? "meeting" : undefined, processing_status: "pending" };
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

it("renders distinct View/Edit request eligibility and pending card states", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([
    { ...event("request_access"), event_id: "eligible", meeting_id: "eligible", subject: "Eligible", can_request_view_access: true, can_request_edit_access: true },
    { ...event("request_access"), event_id: "view-pending", meeting_id: "view-pending", subject: "View pending", pending_access_type: "view" },
    { ...event("view"), event_id: "edit-pending", meeting_id: "edit-pending", subject: "Edit pending", pending_access_type: "edit" },
    { ...event("view"), event_id: "viewer", meeting_id: "viewer", subject: "Viewer", can_request_edit_access: true },
  ]);
  const requestAccess = vi.fn().mockResolvedValue(undefined);
  const requestEditAccess = vi.fn().mockResolvedValue(undefined);
  render(<RecentMeetings token="token" isSubscribed onRequestHistoricalAccess={requestAccess} onRequestMeetingEditAccess={requestEditAccess} />);

  fireEvent.click(await screen.findByRole("button", { name: "Request View" }));
  await waitFor(() => expect(requestAccess).toHaveBeenCalledWith("eligible", "view"));
  await waitFor(() => expect(screen.getAllByRole("button", { name: "Request Edit" })[0]).toBeEnabled());
  fireEvent.click(screen.getAllByRole("button", { name: "Request Edit" })[0]);
  await waitFor(() => expect(requestAccess).toHaveBeenCalledWith("eligible", "edit"));
  fireEvent.click(screen.getAllByRole("button", { name: "Request Edit" })[1]);
  await waitFor(() => expect(requestEditAccess).toHaveBeenCalledWith("viewer"));
  expect(screen.getByText("View Pending")).toBeInTheDocument();
  expect(screen.getByText("Edit Pending")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "View" })).toHaveLength(2);
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

it("publishes calendar rows while processing requests remain pending", async () => {
  vi.mocked(api.getRecentMeetings).mockResolvedValue([event("view")]);
  vi.mocked(api.getProcessingRequests).mockReturnValue(new Promise(() => {}));
  render(<RecentMeetings token="token" isSubscribed />);
  expect(await screen.findByRole("link", { name: "View" })).toBeVisible();
  expect(screen.queryByRole("status", { name: "Recent meetings loading" })).not.toBeInTheDocument();
});
