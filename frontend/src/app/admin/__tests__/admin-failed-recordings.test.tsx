import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getRecordingJobs } from "@/lib/api";
import type { RecordingJobOut } from "@/lib/types";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({
  cleanupAdminJob: vi.fn(), decideMeetingEditAccess: vi.fn(), decideRecordingProcessing: vi.fn(),
  getAdminMeetings: vi.fn(), getAdminUserSyncStatus: vi.fn(), getBusinessUnits: vi.fn(),
  getRecordingJobs: vi.fn(), getRegisteredUsers: vi.fn(), registerUser: vi.fn(), removeUser: vi.fn(),
  reprocessRecordingJob: vi.fn(), revokeAdminMeetingAccess: vi.fn(), updateUser: vi.fn(),
  cancelRecordingJob: vi.fn(), retryRecordingJob: vi.fn(),
}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

function job(overrides: Partial<RecordingJobOut> = {}): RecordingJobOut {
  return {
    job_id: "failed-1", drive_item_id: "recording-1", meeting_id: "meeting-1", title: "Team meeting",
    status: "failed", processing_status: "failed", phase: "failed", review_status: null,
    attempts: 1, max_attempts: 3, error: "raw transcript secret-token https://private.example",
    failure: { stage: "transcription", category: "timeout" },
    can_retry: false, can_cancel: false, can_reprocess: false, processing_enabled: false,
    ...overrides,
  };
}
function openJobs() {
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);
  fireEvent.click(screen.getByText("Processing Jobs"));
}

it("shows bounded failure counts, safe stages and reasons, and meeting links without actions", async () => {
  vi.mocked(getRecordingJobs).mockResolvedValue([
    job(), job({ job_id: "failed-2", meeting_id: null, title: "Unlinked recording", failure: null }),
    job({ job_id: "completed", status: "completed", processing_status: "completed" }),
    job({ job_id: "cancelled", status: "cancelled", processing_status: "cancelled" }),
  ]);
  openJobs();
  const section = await screen.findByRole("region", { name: "Failed recordings" });
  expect(within(section).getByText("Failed recordings (2)")).toBeVisible();
  expect(within(section).getByText(/latest 4 jobs \(up to 200\)/)).toBeVisible();
  expect(within(section).getByText(/a later attempt may have succeeded/)).toBeVisible();
  expect(within(section).getByRole("link", { name: "Team meeting" })).toHaveAttribute("href", "/meetings/meeting-1");
  expect(within(section).getByText(/Transcription failed. Category: Service timed out/)).toBeVisible();
  expect(within(section).getByText(/Failure reason unavailable/)).toBeVisible();
  expect(within(section).getByText(/Meeting not yet available/)).toBeVisible();
  expect(within(section).queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByText(/secret-token|raw transcript|private.example/)).not.toBeInTheDocument();
  expect(getRecordingJobs).toHaveBeenCalledExactlyOnceWith("token", undefined, 200);
});

it("shows an empty state when there are no failed jobs", async () => {
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  openJobs();
  const section = await screen.findByRole("region", { name: "Failed recordings" });
  expect(within(section).getByText("Failed recordings (0)")).toBeVisible();
  expect(within(section).getByText("No failed recording attempts in these jobs.")).toBeVisible();
  const statistics = screen.getByRole("region", { name: "Processing job statistics" });
  expect(within(statistics).getAllByText("0")).toHaveLength(5);
});

it("does not claim zero failures after a failed request and supports reopening to retry", async () => {
  vi.mocked(getRecordingJobs).mockRejectedValueOnce(new Error("sensitive upstream body"))
    .mockResolvedValueOnce([]);
  openJobs();
  expect(await screen.findByText(/Recording jobs could not be loaded/)).toBeVisible();
  expect(screen.queryByRole("region", { name: "Failed recordings" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Processing job statistics" })).not.toBeInTheDocument();
  expect(screen.queryByText(/sensitive upstream body/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Processing Jobs"));
  fireEvent.click(screen.getByText("Processing Jobs"));
  expect(await screen.findByText("Failed recordings (0)")).toBeVisible();
  expect(getRecordingJobs).toHaveBeenCalledTimes(2);
});

it("counts bounded job records by lifecycle status without treating review state as processing", async () => {
  const rows = [
    job({ job_id: "q", status: "pending", processing_status: "queued" }),
    ...(["downloading", "transcribing", "extracting", "processing", "cancel_requested"] as const)
      .map((phase) => job({ job_id: phase, status: "processing", processing_status: phase })),
    job({ job_id: "done", status: "completed", processing_status: "completed", review_status: "awaiting_review" }),
    job({ job_id: "sent", status: "completed", processing_status: "completed", review_status: "sent" }),
    job({ attempts: 3 }), job({ job_id: "cancelled", status: "cancelled", processing_status: "cancelled" }),
  ];
  vi.mocked(getRecordingJobs).mockResolvedValue(rows);
  openJobs();
  const statistics = await screen.findByRole("region", { name: "Processing job statistics" });
  for (const [label, count] of [["Queued", "1"], ["Processing / Transcribing", "5"], ["Completed", "2"], ["Failed", "1"], ["Cancelled", "1"]]) {
    expect(within(statistics).getByText(label).nextElementSibling).toHaveTextContent(count);
  }
  expect(screen.getByText(/Latest 10 job records \(up to 200\)/)).toBeVisible();
  expect(screen.getByText(/A job record may include automatic retries; counts are not execution-attempt totals/)).toBeVisible();
  expect(within(statistics).queryByRole("button")).not.toBeInTheDocument();
  expect(getRecordingJobs).toHaveBeenCalledExactlyOnceWith("token", undefined, 200);
});

it("shows loading without claiming zero counts before the response arrives", async () => {
  vi.mocked(getRecordingJobs).mockReturnValue(new Promise(() => {}));
  openJobs();
  expect(await screen.findByRole("status", { name: "Recording jobs loading" })).toBeVisible();
  expect(screen.queryByRole("region", { name: "Processing job statistics" })).not.toBeInTheDocument();
  expect(screen.queryByText(/No recording jobs yet/)).not.toBeInTheDocument();
});
