import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import DashboardClient from "../dashboard-client";
import type { CalendarEvent, MeetingOut, RecordingJobOut, RecordingProcessingRequest } from "@/lib/types";
import { decideRecordingProcessing, getAllMeetings, getHistoricalMeetings, getProcessingRequests, getRecentMeetings, getRecordingJobs, getSyncStatus, getUpcomingMeetings, syncCalendarsNow } from "@/lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/api", () => ({
  getAllMeetings: vi.fn(), getRecordingJobs: vi.fn(), requestHistoricalAccess: vi.fn(),
  getHistoricalMeetings: vi.fn(), getSyncStatus: vi.fn(), getUpcomingMeetings: vi.fn(),
  getRecentMeetings: vi.fn(), getProcessingRequests: vi.fn(),
  decideRecordingProcessing: vi.fn(),
  cancelRecordingJob: vi.fn(), retryRecordingJob: vi.fn(),
  shareMeeting: vi.fn(), unsubscribeCurrentUser: vi.fn(),
  syncCalendarsNow: vi.fn(),
}));
// A mounted panel must be detectable even when the real component has no jobs.
vi.mock("@/components/recording-jobs", () => ({
  default: () => <section aria-label="Recording processing">Recording processing</section>,
  JobControls: () => null,
  recordingStatusMessage: () => "Recording processing status",
}));
vi.mock("@/components/import-modal", () => ({
  default: () => <div role="dialog" aria-label="Process Past Recording">Recording import</div>,
}));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

const syncCounts = { status: "success" as const, succeeded: 3, failed: 0, skipped: 0, created: 2, updated: 4 };

it("does not repeat a completed calendar sync on a timer", async () => {
  vi.useFakeTimers();
  vi.mocked(syncCalendarsNow).mockResolvedValue(syncCounts);
  vi.mocked(getUpcomingMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]} isAdmin
    upn="admin@example.test" accessToken="offline-test-token" isSubscribed syncStates={[]} loadErrors={[]} />);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sync calendar now" })); });
  await act(async () => { await vi.advanceTimersByTimeAsync(600_000); });
  expect(syncCalendarsNow).toHaveBeenCalledOnce();
  expect(getUpcomingMeetings).toHaveBeenCalledOnce();
});

it("does not replace post-sync calendar results with a slow initial response", async () => {
  let finishInitial!: (events: CalendarEvent[]) => void;
  vi.mocked(getUpcomingMeetings)
    .mockReturnValueOnce(new Promise((resolve) => { finishInitial = resolve; }))
    .mockResolvedValueOnce([calendarEvent({ subject: "After sync" })]);
  vi.mocked(getAllMeetings).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  vi.mocked(syncCalendarsNow).mockResolvedValue(syncCounts);
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]} isAdmin deferInitialLoad
    upn="admin@example.test" accessToken="offline-test-token" isSubscribed syncStates={[]} loadErrors={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Sync calendar now" }));
  expect(await screen.findByText("After sync")).toBeVisible();
  await act(async () => { finishInitial([calendarEvent({ subject: "Before sync" })]); });
  expect(screen.queryByText("Before sync")).not.toBeInTheDocument();
  expect(screen.getByText("After sync")).toBeVisible();
});

it("syncs once per click, blocks duplicate clicks and shows aggregate counts", async () => {
  let finish!: (result: typeof syncCounts) => void;
  vi.mocked(syncCalendarsNow).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  vi.mocked(getUpcomingMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]} isAdmin
    upn="admin@example.test" accessToken="offline-test-token" isSubscribed syncStates={[]} loadErrors={[]} />);

  expect(syncCalendarsNow).not.toHaveBeenCalled();
  const button = screen.getByRole("button", { name: "Sync calendar now" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(syncCalendarsNow).toHaveBeenCalledExactlyOnceWith("offline-test-token");
  expect(screen.getByRole("button", { name: "Syncing calendars…" })).toBeDisabled();
  await act(async () => { finish(syncCounts); });
  expect(screen.getByRole("status")).toHaveTextContent("3 succeeded, 0 failed, 0 skipped; 2 events added, 4 existing events refreshed");
  expect(screen.getByRole("button", { name: "Sync calendar now" })).toBeEnabled();
  expect(getUpcomingMeetings).toHaveBeenCalledOnce();
  expect(getSyncStatus).toHaveBeenCalledOnce();
  expect(syncCalendarsNow).toHaveBeenCalledOnce();
});

it("shows a recoverable sync error without retrying or leaking provider details", async () => {
  vi.mocked(syncCalendarsNow).mockRejectedValueOnce(new Error("SECRET provider response"));
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]} isAdmin
    upn="admin@example.test" accessToken="offline-test-token" isSubscribed syncStates={[]} loadErrors={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Sync calendar now" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Check sync status and existing Microsoft access");
  expect(screen.getByRole("alert")).not.toHaveTextContent("SECRET");
  expect(syncCalendarsNow).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Sync calendar now" })).toBeEnabled();
  vi.mocked(syncCalendarsNow).mockResolvedValueOnce(syncCounts);
  vi.mocked(getUpcomingMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "Sync calendar now" }));
  expect(await screen.findByText(/3 succeeded/)).toBeVisible();
  expect(syncCalendarsNow).toHaveBeenCalledTimes(2);
});

it("reports partial failures and skipped users without hiding success counts", async () => {
  vi.mocked(syncCalendarsNow).mockResolvedValue({ ...syncCounts, status: "partial", succeeded: 1, failed: 1, skipped: 1 });
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  vi.mocked(getUpcomingMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]} isAdmin
    upn="admin@example.test" accessToken="offline-test-token" isSubscribed syncStates={[]} loadErrors={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Sync calendar now" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("1 succeeded, 1 failed, 1 skipped");
  expect(syncCalendarsNow).toHaveBeenCalledOnce();
});

it.each([{ isAdmin: false, isSubscribed: true }, { isAdmin: true, isSubscribed: false }])(
  "hides the sync action without the required caller authorization: %j", (authorization) => {
    render(<DashboardClient meetings={[]} upcoming={[]} historical={[]} {...authorization}
      upn="reviewer@example.test" accessToken="offline-test-token" syncStates={[]} loadErrors={[]} />);
    expect(screen.queryByRole("button", { name: "Sync calendar now" })).not.toBeInTheDocument();
    expect(syncCalendarsNow).not.toHaveBeenCalled();
  },
);

function processingRequest(overrides: Partial<RecordingProcessingRequest> = {}): RecordingProcessingRequest {
  return {
    id: "request-1", event_id: "event-1", subject: "Cross-user recording", start: null, end: null,
    organizer_email: "owner@example.test", requester_user_id: "requester-1", requester_name: "Wei Jiuyang",
    status: "pending", can_decide: true, created_at: "2026-09-08T08:00:00Z", decided_at: null, meeting_id: null,
    ...overrides,
  };
}

function calendarEvent(overrides: Partial<CalendarEvent>): CalendarEvent {
  return {
    event_id: "event",
    subject: "Meeting",
    start: null,
    start_tz: "UTC",
    end: null,
    organizer_name: null,
    organizer_email: null,
    attendees: [],
    attendee_count: 0,
    platform: "Teams",
    location: null,
    status: "upcoming",
    ...overrides,
  };
}

function processedMeeting(overrides: Partial<MeetingOut> = {}): MeetingOut {
  return {
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
    ...overrides,
  };
}

function recordingJob(overrides: Partial<RecordingJobOut> = {}): RecordingJobOut {
  return {
    job_id: "job-1",
    drive_item_id: "item-1",
    meeting_id: null,
    title: "Queued recording",
    status: "pending",
    processing_status: "queued",
    review_status: null,
    phase: "queued",
    attempts: 0,
    max_attempts: 3,
    error: null,
    can_retry: false,
    can_cancel: true,
    can_reprocess: false,
    processing_enabled: false,
    ...overrides,
  };
}

it("renders the dashboard frame while slow dashboard data loads asynchronously", async () => {
  let finishUpcoming!: (events: CalendarEvent[]) => void;
  vi.mocked(getAllMeetings).mockResolvedValue([]);
  vi.mocked(getHistoricalMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  vi.mocked(getUpcomingMeetings).mockReturnValue(new Promise((resolve) => { finishUpcoming = resolve; }));

  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} deferInitialLoad />);

  expect(screen.getByRole("heading", { name: "Meeting Intelligence" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Calendar meetings loading" })).toHaveTextContent("Loading calendar meetings");
  expect(getUpcomingMeetings).toHaveBeenCalledWith("offline-test-token");
  expect(getHistoricalMeetings).not.toHaveBeenCalled();

  finishUpcoming([calendarEvent({ subject: "Loaded later" })]);
  expect(await screen.findByText("Loaded later")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
});

it("shows a calendar failure without waiting for unrelated recording status", async () => {
  vi.mocked(getAllMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockReturnValue(new Promise(() => {}));
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  vi.mocked(getUpcomingMeetings).mockRejectedValue(new Error("Calendar unavailable"));

  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} deferInitialLoad />);

  expect(await screen.findByText("Calendar sync failed: Calendar unavailable")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Meeting Intelligence" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Recording status loading" })).toHaveTextContent("Loading recording status");
  expect(screen.queryByRole("status", { name: "Calendar meetings loading" })).not.toBeInTheDocument();
  expect(screen.queryByText("No upcoming meetings")).not.toBeInTheDocument();
});

it.each(["meetings", "sync", "jobs"] as const)("finishes an empty calendar while %s is still loading", async (pendingSource) => {
  vi.mocked(getAllMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  vi.mocked(getUpcomingMeetings).mockResolvedValue([]);
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  const pending = new Promise<never>(() => {});
  if (pendingSource === "meetings") vi.mocked(getAllMeetings).mockReturnValue(pending);
  if (pendingSource === "sync") vi.mocked(getSyncStatus).mockReturnValue(pending);
  if (pendingSource === "jobs") vi.mocked(getRecordingJobs).mockReturnValue(pending);

  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} deferInitialLoad />);

  expect(await screen.findByText("No upcoming meetings")).toBeVisible();
  expect(screen.queryByRole("status", { name: "Calendar meetings loading" })).not.toBeInTheDocument();
  const label = { meetings: "Meeting records", sync: "Sync status", jobs: "Recording status" }[pendingSource];
  expect(screen.getByRole("status", { name: `${label} loading` })).toBeVisible();
  if (pendingSource === "meetings") {
    fireEvent.click(screen.getByRole("button", { name: "Old Meetings" }));
    expect(screen.queryByText("No completed meetings yet")).not.toBeInTheDocument();
  }
});

it("shows returned reviews and recording jobs while calendar and sync status remain pending", async () => {
  vi.mocked(getAllMeetings).mockResolvedValue([processedMeeting({ title: "Ready review" })]);
  vi.mocked(getRecordingJobs).mockResolvedValue([recordingJob()]);
  vi.mocked(getSyncStatus).mockReturnValue(new Promise(() => {}));
  vi.mocked(getUpcomingMeetings).mockReturnValue(new Promise(() => {}));
  vi.mocked(getProcessingRequests).mockResolvedValue([]);

  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} deferInitialLoad />);

  fireEvent.click(screen.getByRole("button", { name: "Awaiting Review" }));
  expect(await screen.findByText("Ready review")).toBeVisible();
  expect(screen.queryByRole("status", { name: "Meeting records loading" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^In Progress/ }));
  expect(screen.getByText("Queued recording")).toBeVisible();
  expect(screen.queryByRole("status", { name: "Recording status loading" })).not.toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Calendar meetings loading" })).toBeVisible();
  expect(screen.getByRole("status", { name: "Sync status loading" })).toBeVisible();
});

it.each(["meetings", "sync", "jobs"] as const)("keeps calendar results visible when %s fails independently", async (failureSource) => {
  vi.mocked(getAllMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  vi.mocked(getUpcomingMeetings).mockResolvedValue([calendarEvent({ subject: "Available calendar meeting" })]);
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  if (failureSource === "meetings") vi.mocked(getAllMeetings).mockRejectedValue(new Error("Meeting records unavailable"));
  if (failureSource === "sync") vi.mocked(getSyncStatus).mockRejectedValue(new Error("Sync state unavailable"));
  if (failureSource === "jobs") vi.mocked(getRecordingJobs).mockRejectedValue(new Error("Recording status unavailable"));

  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} deferInitialLoad />);

  expect(await screen.findByText("Available calendar meeting")).toBeVisible();
  const heading = {
    meetings: "Meeting data is temporarily unavailable",
    sync: "Sync status is temporarily unavailable",
    jobs: "Recording status is temporarily unavailable",
  }[failureSource];
  expect(screen.getByText(heading)).toBeVisible();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("does not load calendar data or show a calendar loader for an unsubscribed user", async () => {
  vi.mocked(getAllMeetings).mockResolvedValue([]);
  vi.mocked(getSyncStatus).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  vi.mocked(getProcessingRequests).mockResolvedValue([]);

  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={false} syncStates={[]} loadErrors={[]} deferInitialLoad />);

  expect(screen.getByText("Calendar processing is off")).toBeVisible();
  expect(screen.queryByRole("status", { name: "Calendar meetings loading" })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  expect(getUpcomingMeetings).not.toHaveBeenCalled();
});

it("loads historical meetings once when Old Meetings is first opened and preserves their rendering", async () => {
  const historical = processedMeeting({ id: "historical-1", title: "Historical client meeting", state: "sent", recorded_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString() });
  vi.mocked(getHistoricalMeetings).mockResolvedValue([historical]);
  vi.mocked(getRecentMeetings).mockResolvedValue([]);

  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  expect(getHistoricalMeetings).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Old Meetings" }));
  expect(getHistoricalMeetings).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("status")).toHaveTextContent("Loading historical meetings");
  await waitFor(() => expect(screen.queryByText("Loading historical meetings…")).not.toBeInTheDocument());

  fireEvent.click(screen.getByRole("button", { name: "Meetings" }));
  expect(await screen.findByText("Historical client meeting")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Old Meetings" }));
  expect(getHistoricalMeetings).toHaveBeenCalledTimes(1);
});

it("keeps the dashboard stats, meeting tabs and import entry without the persistent job panel", () => {
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  for (const label of ["Upcoming", "In Progress", "Awaiting Review", "Completed"]) {
    expect(screen.getAllByRole("button", { name: new RegExp(label) }).length).toBeGreaterThan(0);
  }
  expect(screen.getByRole("button", { name: "Old Meetings" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Recording processing" })).not.toBeInTheDocument();
  expect(screen.queryByText("Recording processing")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Process Past Recording" }));
  expect(screen.getByRole("dialog", { name: "Process Past Recording" })).toBeInTheDocument();
});

it("excludes ended events from Upcoming Meetings while keeping future and in-progress events", () => {
  const now = Date.now();
  render(<DashboardClient meetings={[]} historical={[]}
    upcoming={[
      calendarEvent({ event_id: "ended", subject: "Ended meeting", end: new Date(now - 60_000).toISOString() }),
      calendarEvent({ event_id: "future", subject: "Future meeting", end: new Date(now + 60_000).toISOString() }),
      calendarEvent({ event_id: "live", subject: "Live meeting", end: new Date(now + 60_000).toISOString(), status: "in_progress" }),
    ]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  expect(screen.queryByText("Ended meeting")).not.toBeInTheDocument();
  expect(screen.getByText("Future meeting")).toBeInTheDocument();

  fireEvent.click(screen.getAllByRole("button", { name: /In Progress/ })[1]);
  expect(screen.getByText("Live meeting")).toBeInTheDocument();
});

it("counts persisted meetings from calendar participants", () => {
  render(<DashboardClient meetings={[processedMeeting()]} upcoming={[]} historical={[]}
    upn="wei.jiuyang@taxconsulting.co.za" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  fireEvent.click(screen.getAllByRole("button", { name: /Awaiting Review/ })[1]);

  expect(screen.getByText("2 participants")).toBeInTheDocument();
});

it("renders pending recording processing requests with owner-only approval actions", async () => {
  vi.mocked(getProcessingRequests).mockResolvedValue([
    processingRequest(),
    processingRequest({ id: "request-2", subject: "Someone else's recording", requester_name: "Other Requester", can_decide: false }),
    processingRequest({ id: "request-3", subject: "Already approved", status: "approved" }),
  ]);
  vi.mocked(decideRecordingProcessing).mockResolvedValue(processingRequest({ status: "approved" }));
  render(<DashboardClient meetings={[processedMeeting()]} upcoming={[]} historical={[]}
    upn="owner@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  await waitFor(() => expect(getProcessingRequests).toHaveBeenCalledWith("offline-test-token"));
  fireEvent.click(screen.getAllByRole("button", { name: /Awaiting Review/ })[1]);

  expect(screen.getByRole("heading", { name: "Existing AI Notes Reviews" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Recording Processing Requests" })).toBeInTheDocument();
  expect(screen.getByText("Requested by: Wei Jiuyang")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  expect(screen.getByText("Someone else's recording").parentElement).not.toHaveTextContent("Approve");
  expect(screen.queryByText("Already approved")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(decideRecordingProcessing).toHaveBeenCalledWith("request-1", true, "offline-test-token"));
});

it("counts active recording jobs and does not duplicate their linked meeting fallback", () => {
  const meeting = processedMeeting({ id: "processing-meeting", title: "Transcribing meeting", state: "transcribing" });
  const linkedJob = recordingJob({
    job_id: "job-linked",
    meeting_id: meeting.id,
    title: meeting.title,
    status: "processing",
    processing_status: "transcribing",
    phase: "transcribing",
    processing_enabled: true,
  });
  render(<DashboardClient meetings={[meeting]} recordingJobs={[linkedJob, recordingJob()]} upcoming={[]} historical={[]}
    upn="wei.jiuyang@taxconsulting.co.za" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  const inProgressButtons = screen.getAllByRole("button", { name: /In Progress/ });
  expect(inProgressButtons[0]).toHaveTextContent("2");
  expect(inProgressButtons[1]).toHaveTextContent("2");
  fireEvent.click(inProgressButtons[1]);

  expect(screen.getAllByText("Transcribing meeting")).toHaveLength(1);
  expect(screen.getByText("Queued recording")).toBeInTheDocument();
});

it("does not poll reviews or recording jobs without active processing", () => {
  vi.useFakeTimers();
  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  act(() => vi.advanceTimersByTime(20_000));
  expect(getAllMeetings).not.toHaveBeenCalled();
  expect(getRecordingJobs).not.toHaveBeenCalled();
});

it("pauses active polling while hidden or while the import modal owns job refreshes", () => {
  vi.useFakeTimers();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  render(<DashboardClient meetings={[]} recordingJobs={[recordingJob()]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  act(() => vi.advanceTimersByTime(10_000));
  expect(getRecordingJobs).not.toHaveBeenCalled();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  fireEvent.click(screen.getByRole("button", { name: "Process Past Recording" }));
  act(() => vi.advanceTimersByTime(10_000));
  expect(getRecordingJobs).not.toHaveBeenCalled();
});

it("does not overlap active dashboard polling requests", () => {
  vi.useFakeTimers();
  vi.mocked(getRecordingJobs).mockReturnValue(new Promise(() => {}));
  vi.mocked(getAllMeetings).mockReturnValue(new Promise(() => {}));
  render(<DashboardClient meetings={[]} recordingJobs={[recordingJob()]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  act(() => vi.advanceTimersByTime(20_000));
  expect(getRecordingJobs).toHaveBeenCalledOnce();
  expect(getAllMeetings).toHaveBeenCalledOnce();
});

it.each(["jobs", "meetings"] as const)("preserves loaded data when refreshing %s fails and allows retry", async (failureSource) => {
  vi.useFakeTimers();
  const previous = processedMeeting({ title: "Previously loaded meeting" });
  const updated = processedMeeting({ title: "Updated meeting" });
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  vi.mocked(getAllMeetings).mockResolvedValue([updated]);
  if (failureSource === "jobs") {
    vi.mocked(getRecordingJobs).mockRejectedValueOnce(new Error("SECRET network failure"));
  } else {
    vi.mocked(getAllMeetings).mockRejectedValueOnce(new Error("SECRET network failure"));
  }
  render(<DashboardClient meetings={[previous]} recordingJobs={[recordingJob()]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);
  fireEvent.click(screen.getByRole("button", { name: /^Awaiting Review/ }));

  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(screen.getByText("Previously loaded meeting")).toBeVisible();
  expect(screen.queryByText("Updated meeting")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^In Progress/ })).toHaveTextContent("1");
  const warning = screen.getByRole("status", { name: "Dashboard refresh status" });
  expect(warning).toHaveTextContent("Your last loaded meeting and recording information is still shown.");
  expect(warning).not.toHaveTextContent("SECRET");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();

  let rejectRetry!: (error: Error) => void;
  vi.mocked(getRecordingJobs).mockReturnValueOnce(new Promise((_, reject) => { rejectRetry = reject; }));
  fireEvent.click(screen.getByRole("button", { name: "Retry refresh" }));
  const busy = screen.getByRole("button", { name: "Retrying…" });
  expect(busy).toBeDisabled();
  fireEvent.click(busy);
  expect(getRecordingJobs).toHaveBeenCalledTimes(2);
  expect(getAllMeetings).toHaveBeenCalledTimes(2);
  expect(screen.getByText("Previously loaded meeting")).toBeVisible();
  await act(async () => { rejectRetry(new Error("SECRET retry failure")); });
  expect(screen.getByRole("button", { name: "Retry refresh" })).toBeEnabled();
  expect(screen.getByText("Previously loaded meeting")).toBeVisible();

  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry refresh" })); });
  expect(screen.getByText("Updated meeting")).toBeVisible();
  expect(screen.queryByText("Previously loaded meeting")).not.toBeInTheDocument();
  expect(screen.queryByRole("status", { name: "Dashboard refresh status" })).not.toBeInTheDocument();
  expect(getRecordingJobs).toHaveBeenCalledTimes(3);
  expect(getAllMeetings).toHaveBeenCalledTimes(3);
});

it("clears the refresh warning after the next successful automatic refresh", async () => {
  vi.useFakeTimers();
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockRejectedValueOnce(new Error("Temporary failure")).mockResolvedValue([recordingJob()]);
  vi.mocked(getAllMeetings).mockResolvedValue([processedMeeting({ title: "Refreshed meeting" })]);
  render(<DashboardClient meetings={[]} recordingJobs={[recordingJob()]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);
  fireEvent.click(screen.getByRole("button", { name: /^Awaiting Review/ }));
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(screen.getByRole("status", { name: "Dashboard refresh status" })).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(screen.queryByRole("status", { name: "Dashboard refresh status" })).not.toBeInTheDocument();
  expect(screen.getByText("Refreshed meeting")).toBeVisible();
});

it("keeps Meetings mounted after its first visit", async () => {
  vi.mocked(getRecentMeetings).mockResolvedValue([]);
  vi.mocked(getProcessingRequests).mockResolvedValue([]);
  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  expect(getRecentMeetings).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Meetings" }));
  expect(await screen.findByText("No meetings match these filters.")).toBeInTheDocument();
  expect(getRecentMeetings).toHaveBeenCalledOnce();
  expect(getProcessingRequests).toHaveBeenCalledOnce();

  fireEvent.click(screen.getByRole("button", { name: "Upcoming Meetings" }));
  fireEvent.click(screen.getByRole("button", { name: "Meetings" }));
  expect(screen.getByText("No meetings match these filters.")).toBeInTheDocument();
  await waitFor(() => expect(getRecentMeetings).toHaveBeenCalledOnce());
  expect(getProcessingRequests).toHaveBeenCalledOnce();
});

it("shows a single Meetings tab without Historical Access", () => {
  render(<DashboardClient meetings={[]} recordingJobs={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);
  expect(screen.getByRole("button", { name: "Meetings" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Historical Access/ })).not.toBeInTheDocument();
});

it("shows Share for an organizer when UPN casing differs", () => {
  render(<DashboardClient meetings={[processedMeeting({ state: "sent", organizer_upn: "OWNER@EXAMPLE.TEST" })]} upcoming={[]} historical={[]}
    upn="owner@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  fireEvent.click(screen.getByRole("button", { name: "Old Meetings" }));

  expect(screen.getByRole("button", { name: /Share/ })).toBeInTheDocument();
});
