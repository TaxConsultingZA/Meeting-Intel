import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ImportModal from "../import-modal";
import { getAvailableRecordings, getRecordingJobs, reprocessRecording } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getAvailableRecordings: vi.fn(),
  getRecordingJobs: vi.fn(),
  importRecording: vi.fn(),
  reprocessRecording: vi.fn(),
  cancelRecordingJob: vi.fn(),
  retryRecordingJob: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const cachedRecording = {
  drive_item_id: "cached-item", drive_id: "drive-1", name: "cached.mp4", size: 1024,
  created_at: "2026-09-02T08:15:00Z", already_imported: false,
  meeting_id: null, meeting_state: null, meeting_error: null,
};

it("shows completed processing separately from awaiting review", async () => {
  vi.mocked(getAvailableRecordings).mockResolvedValue([{
    drive_item_id: "item-1",
    drive_id: "drive-1",
    name: "test.mp4",
    size: 1024,
    created_at: "2026-09-02T08:15:00Z",
    already_imported: true,
    meeting_id: "meeting-1",
    meeting_state: "awaiting_review",
    meeting_error: null,
  }]);
  vi.mocked(getRecordingJobs).mockResolvedValue([{
    job_id: "job-1",
    drive_item_id: "item-1",
    meeting_id: "meeting-1",
    title: "test",
    status: "completed",
    processing_status: "completed",
    review_status: "awaiting_review",
    phase: "completed",
    attempts: 1,
    max_attempts: 3,
    error: null,
    can_retry: false,
    can_cancel: false,
    can_reprocess: true,
    processing_enabled: false,
  }]);

  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} />);

  await waitFor(() => expect(screen.getByText("Completed")).toBeInTheDocument());
  expect(screen.getByRole("columnheader", { name: "Processing" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Review" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
  expect(screen.getByText("Awaiting Review")).toBeInTheDocument();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Reprocess" }));
  await waitFor(() => expect(reprocessRecording).toHaveBeenCalledWith("item-1", "drive-1", "owner@taxconsulting.co.za"));
  expect(screen.getByRole("link", { name: "View" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
});

it("shows approved completed recordings as view-only", async () => {
  vi.mocked(getAvailableRecordings).mockResolvedValue([{
    drive_item_id: "item-2", drive_id: "drive-1", name: "approved.mp4", size: 2048,
    created_at: "2026-09-02T08:15:00Z", already_imported: true,
    meeting_id: "meeting-2", meeting_state: "approved", meeting_error: null,
  }]);
  vi.mocked(getRecordingJobs).mockResolvedValue([{
    job_id: "job-2", drive_item_id: "item-2", meeting_id: "meeting-2", title: "approved",
    status: "completed", processing_status: "completed", review_status: "approved",
    phase: "completed", attempts: 1, max_attempts: 3, error: null,
    can_retry: false, can_cancel: false, can_reprocess: false, processing_enabled: false,
  }]);

  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} />);

  await waitFor(() => expect(screen.getByText("Approved")).toBeInTheDocument());
  expect(screen.getByText("Completed")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Reprocess" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
});

it("uses successful recordings supplied by the Dashboard without fetching available again", async () => {
  vi.mocked(getAvailableRecordings).mockResolvedValue([cachedRecording]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  const onRecordingsLoaded = vi.fn();
  const first = render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} onRecordingsLoaded={onRecordingsLoaded} />);

  expect(await screen.findByText("cached")).toBeInTheDocument();
  await waitFor(() => expect(onRecordingsLoaded).toHaveBeenCalled());
  const cached = onRecordingsLoaded.mock.calls.at(-1)?.[0];
  expect(getAvailableRecordings).toHaveBeenCalledOnce();
  first.unmount();

  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} initialRecordings={cached} onRecordingsLoaded={vi.fn()} />);
  expect(screen.getByText("cached")).toBeInTheDocument();
  await waitFor(() => expect(getAvailableRecordings).toHaveBeenCalledOnce());
});

it("keeps cached recordings visible when an explicit refresh fails", async () => {
  vi.mocked(getAvailableRecordings).mockRejectedValue(new Error("OneDrive unavailable"));
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} initialRecordings={[cachedRecording]} />);

  expect(screen.getByText("cached")).toBeInTheDocument();
  expect(getAvailableRecordings).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Showing the previously loaded recordings");
  expect(screen.getByText("cached")).toBeInTheDocument();
  expect(getAvailableRecordings).toHaveBeenCalledOnce();
});
