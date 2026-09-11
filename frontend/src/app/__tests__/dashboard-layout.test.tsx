import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import DashboardClient from "../dashboard-client";
import type { CalendarEvent, MeetingOut, RecordingJobOut, RecordingProcessingRequest } from "@/lib/types";
import { decideRecordingProcessing, getAllMeetings, getHistoricalMeetings, getProcessingRequests, getRecentMeetings, getRecordingJobs, getSyncStatus, getUpcomingMeetings } from "@/lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/api", () => ({
  getAllMeetings: vi.fn(), getRecordingJobs: vi.fn(), requestHistoricalAccess: vi.fn(),
  getHistoricalMeetings: vi.fn(), getSyncStatus: vi.fn(), getUpcomingMeetings: vi.fn(),
  getRecentMeetings: vi.fn(), getProcessingRequests: vi.fn(),
  decideRecordingProcessing: vi.fn(),
  cancelRecordingJob: vi.fn(), retryRecordingJob: vi.fn(),
  shareMeeting: vi.fn(), unsubscribeCurrentUser: vi.fn(),
}));
// A mounted panel must be detectable even when the real component has no jobs.
vi.mock("@/components/recording-jobs", () => ({
  default: () => <section aria-label="Recording processing">Recording processing</section>,
  JobControls: () => null,
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
  expect(screen.getByRole("status")).toHaveTextContent("Loading dashboard data");
  expect(getUpcomingMeetings).toHaveBeenCalledWith("offline-test-token");

  finishUpcoming([calendarEvent({ subject: "Loaded later" })]);
  expect(await screen.findByText("Loaded later")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
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
