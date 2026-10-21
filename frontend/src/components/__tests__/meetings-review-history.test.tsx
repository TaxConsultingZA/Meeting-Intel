import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DashboardClient from "@/app/dashboard-client";
import RecentMeetings from "../recent-meetings";
import * as api from "@/lib/api";
import type { MeetingOut, RecentMeeting } from "@/lib/types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  getAllMeetings: vi.fn(), getRecentMeetings: vi.fn(), getHistoricalMeetings: vi.fn(),
  getRecordingJobs: vi.fn(), getProcessingRequests: vi.fn(), getUpcomingMeetings: vi.fn(),
  getSyncStatus: vi.fn(), getCalendarSyncRun: vi.fn(), syncCalendarsNow: vi.fn(),
}));
vi.mock("@/components/recording-jobs", () => ({
  default: () => null, JobControls: () => null, recordingStatusMessage: () => "",
}));
vi.mock("@/components/import-modal", () => ({ default: () => null }));

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  vi.mocked(api.getRecentMeetings).mockResolvedValue([]);
  vi.mocked(api.getHistoricalMeetings).mockResolvedValue([]);
  vi.mocked(api.getProcessingRequests).mockResolvedValue([]);
  vi.mocked(api.getRecordingJobs).mockResolvedValue([]);
  vi.mocked(api.getUpcomingMeetings).mockResolvedValue([]);
  vi.mocked(api.getSyncStatus).mockResolvedValue([]);
  vi.mocked(api.getCalendarSyncRun).mockResolvedValue(null);
});

function meeting(id: string, title: string, recordedAt: string): MeetingOut {
  return { id, title, recorded_at: recordedAt, state: "awaiting_review", summary: null,
    action_items: [], calendar_participants: [], organizer_upn: "host@external.example",
    email_recipients: [], approved_recipients: [], is_organizer: false, can_edit: false,
    can_request_edit_access: true, edit_access_status: "none", edit_access_requests: [],
    speaker_candidates: [], speaker_mappings: {}, speaker_sample_labels: [] };
}

function showAll() {
  fireEvent.change(screen.getByRole("combobox", { name: "Time" }), { target: { value: "all" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Recording" }), { target: { value: "all" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Organizer" }), { target: { value: "all" } });
}

it("shows the same authorised review IDs in Meetings when calendar and historical sources are empty", async () => {
  // Synthetic IDs only; these reproduce the screenshot's dates, not live identities.
  const stored = [
    meeting("fixture-trust", "Trust IT3(t) Reporting – Practical Classroom Session", "2026-09-01T08:00:00Z"),
    meeting("fixture-test", "test", "2026-09-02T08:00:00Z"),
    meeting("fixture-alignment", "Meeting-Intel Alignment", "2026-08-21T08:00:00Z"),
  ];
  vi.mocked(api.getAllMeetings).mockResolvedValue(stored);
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]} deferInitialLoad
    upn="attendee@example.test" accessToken="offline-token" isSubscribed syncStates={[]} loadErrors={[]} />);
  fireEvent.click(await screen.findByRole("button", { name: "Awaiting Review3" }));
  for (const item of stored) expect(await screen.findByRole("link", { name: new RegExp(item.title === "test" ? "^test" : item.title!.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) })).toHaveAttribute("href", `/meetings/${item.id}`);
  fireEvent.click(screen.getByRole("button", { name: "Meetings" }));
  showAll();
  const list = screen.getByRole("region", { name: "Meetings" });
  for (const item of stored) {
    expect(await within(list).findByRole("heading", { name: item.title! })).toBeVisible();
    expect(list.querySelector(`a[href="/meetings/${item.id}"]`)).not.toBeNull();
  }
  expect(within(list).getAllByRole("heading", { level: 3 }).slice(0, 3).map(node => node.textContent))
    .toEqual(["test", stored[0].title, "Meeting-Intel Alignment"]);
  expect(screen.queryByText("Not authorised fixture")).not.toBeInTheDocument();
  expect(api.getAllMeetings).toHaveBeenCalledOnce();
  expect(api.getHistoricalMeetings).toHaveBeenCalledOnce();
  expect(api.syncCalendarsNow).not.toHaveBeenCalled();
});

it.each(["queued", "downloading", "transcribing", "extracting", "awaiting_review", "approved", "sent", "failed", "cancelled"] as const)(
  "includes an authorised stored %s meeting in All even without a calendar record or date", async (state) => {
    const stored = { ...meeting(`state-${state}`, `Stored ${state}`, ""), state, recorded_at: null };
    render(<RecentMeetings token="offline-token" isSubscribed accessibleMeetings={[stored]} />);
    showAll();
    expect(await screen.findByRole("heading", { name: `Stored ${state}` })).toBeVisible();
    expect(screen.getByRole("link", { name: "View" })).toHaveAttribute("href", `/meetings/state-${state}`);
  },
);

it.each([
  ["past beyond thirty days", -400, "ended"],
  ["future beyond seven days", 400, "upcoming"],
  ["in progress", 0, "in_progress"],
] as const)("includes an acquired calendar event %s without a recording", async (label, days, status) => {
  const date = new Date(Date.now() + days * 86400000).toISOString();
  const calendar: RecentMeeting = { event_id: label, subject: label, start: date, end: date, start_tz: "UTC",
    status, action: "no_recording", organizer_email: "host@external.example", organizer_name: "Host",
    attendees: [], attendee_count: 0, platform: "Teams", location: null };
  vi.mocked(api.getRecentMeetings).mockResolvedValue([calendar]);
  render(<RecentMeetings token="offline-token" isSubscribed />);
  showAll();
  expect(await screen.findByRole("heading", { name: label })).toBeVisible();
  expect(api.getRecentMeetings).toHaveBeenCalledWith("offline-token", true);
  expect(screen.queryByRole("link", { name: "View" })).not.toBeInTheDocument();
});

it("loads restricted historical summaries on Meetings entry without requiring the history tab", async () => {
  const restricted = meeting("historical-candidate", "Access required record", "2000-01-01T08:00:00Z");
  vi.mocked(api.getHistoricalMeetings).mockResolvedValue([restricted]);
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]} upn="attendee@example.test"
    accessToken="offline-token" isSubscribed syncStates={[]} loadErrors={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Meetings" }));
  showAll();
  expect(await screen.findByRole("heading", { name: restricted.title! })).toBeVisible();
  expect(screen.getByRole("button", { name: "Request Access" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "View" })).not.toBeInTheDocument();
  expect(api.getHistoricalMeetings).toHaveBeenCalledOnce();
  expect(api.syncCalendarsNow).not.toHaveBeenCalled();
});

it("does not treat a legacy thirty-day browser cache as a complete calendar catalog", async () => {
  sessionStorage.setItem("meeting-intel:recent-meetings:v3:current-user", JSON.stringify({
    version: 3, cachedAt: Date.now(), events: [],
  }));
  vi.mocked(api.getRecentMeetings).mockRejectedValue(new Error("Offline fixture failure"));
  render(<RecentMeetings token="offline-token" isSubscribed />);
  showAll();
  expect(await screen.findByRole("alert")).toHaveTextContent("Meetings unavailable");
});

it("deduplicates stable IDs without merging distinct meetings with identical titles, dates and organisers", async () => {
  const date = new Date(Date.now() - 86400000).toISOString();
  const first = meeting("first", "Same title", date);
  const second = meeting("second", "Same title", date);
  const historical = meeting("historical", "Same title", date);
  const calendar: RecentMeeting = { event_id: "unbound-event", subject: "Same title", start: date, end: date,
    start_tz: "UTC", status: "ended", action: "no_recording", organizer_email: first.organizer_upn ?? null,
    organizer_name: "Host", attendees: [], attendee_count: 0, platform: "Teams", location: null };
  vi.mocked(api.getRecentMeetings).mockResolvedValue([
    { ...calendar, event_id: "bound-event", meeting_id: "first", subject: "Calendar duplicate", action: "view" },
    calendar, calendar,
  ]);
  render(<RecentMeetings token="offline-token" isSubscribed accessibleMeetings={[first, first, second]}
    historical={[{ ...first, title: "Historical duplicate" }, historical, historical]} onRequestHistoricalAccess={vi.fn()} />);
  showAll();
  await waitFor(() => expect(screen.getAllByRole("heading", { name: "Same title" })).toHaveLength(4));
  expect(screen.queryByText("Calendar duplicate")).not.toBeInTheDocument();
  expect(screen.queryByText("Historical duplicate")).not.toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "View" }).map(link => link.getAttribute("href")))
    .toEqual(["/meetings/first", "/meetings/second"]);
  expect(screen.getByRole("button", { name: "Request Access" })).toBeInTheDocument();
});

it("applies existing time, recording and organiser filters to stored review meetings", async () => {
  const recent = new Date(Date.now() - 86400000).toISOString();
  const older = new Date(Date.now() - 15 * 86400000).toISOString();
  render(<RecentMeetings token="offline-token" cacheIdentity="attendee@example.test" isSubscribed
    accessibleMeetings={[
      { ...meeting("mine", "My review", recent), organizer_upn: "attendee@example.test" },
      { ...meeting("other", "Approved record", recent), state: "approved" },
      { ...meeting("old", "Older review", older), state: "sent" },
    ]} />);
  expect(await screen.findByText("My review")).toBeInTheDocument();
  expect(screen.getByText("Approved record")).toBeInTheDocument();
  expect(screen.queryByText("Older review")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Time" }), { target: { value: "30" } });
  expect(screen.getByText("Older review")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Organizer" }), { target: { value: "me" } });
  expect(screen.queryByText("Approved record")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Organizer" }), { target: { value: "others" } });
  expect(screen.queryByText("My review")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Recording" }), { target: { value: "without" } });
  expect(screen.queryByText("Older review")).not.toBeInTheDocument();
});
