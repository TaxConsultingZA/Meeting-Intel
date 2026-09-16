import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanupAdminJob, getRecordingJobs } from "@/lib/api";
import type { RecordingJobOut } from "@/lib/types";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({
  cleanupAdminJob: vi.fn(), decideMeetingEditAccess: vi.fn(), decideRecordingProcessing: vi.fn(),
  getAdminMeetings: vi.fn(), getAdminUserSyncStatus: vi.fn(), getBusinessUnits: vi.fn(),
  getRecordingJobs: vi.fn(), getRegisteredUsers: vi.fn(), registerUser: vi.fn(), removeUser: vi.fn(),
  reprocessRecordingJob: vi.fn(), revokeAdminMeetingAccess: vi.fn(), updateUser: vi.fn(),
}));
vi.mock("@/components/recording-jobs", () => ({ JobControls: () => <span>Existing controls</span> }));

afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

function job(status: "pending" | RecordingJobOut["processing_status"]): RecordingJobOut {
  const processingStatus = status === "pending" ? "queued" : status;
  return {
    job_id: `job-${status}`, drive_item_id: "item", meeting_id: "meeting", title: `${status} job`,
    status, processing_status: processingStatus, review_status: null, phase: processingStatus, attempts: 1, max_attempts: 3,
    error: null, can_retry: status === "failed", can_cancel: status === "pending",
    can_reprocess: false, processing_enabled: true,
  };
}

it("requires confirmation and offers cleanup only for eligible jobs", async () => {
  const initialJobs = [job("failed"), job("cancelled"), job("pending"), job("processing"), job("completed")];
  vi.mocked(getRecordingJobs)
    .mockResolvedValueOnce(initialJobs)
    .mockResolvedValueOnce(initialJobs.filter((entry) => entry.status !== "failed"));
  vi.mocked(cleanupAdminJob).mockResolvedValue();
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);

  fireEvent.click(screen.getByText("Processing Jobs"));
  expect(await screen.findAllByRole("button", { name: "Clean up" })).toHaveLength(2);
  fireEvent.click(screen.getAllByRole("button", { name: "Clean up" })[0]);
  expect(cleanupAdminJob).not.toHaveBeenCalled();
  fireEvent.click(screen.getAllByRole("button", { name: "Clean up" })[0]);

  await waitFor(() => expect(cleanupAdminJob).toHaveBeenCalledWith("job-failed", "token"));
  await waitFor(() => expect(getRecordingJobs).toHaveBeenCalledTimes(2));
  expect(confirm).toHaveBeenCalledWith("Remove this failed operational job record? Saved meeting content will be kept.");
  expect(screen.getAllByText("Existing controls")).toHaveLength(4);
});

it("shows a clear error when cleanup is rejected", async () => {
  vi.mocked(getRecordingJobs).mockResolvedValue([job("failed")]);
  vi.mocked(cleanupAdminJob).mockRejectedValue(new Error("Job history linked to a processing request cannot be cleaned up"));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);

  fireEvent.click(screen.getByText("Processing Jobs"));
  fireEvent.click(await screen.findByRole("button", { name: "Clean up" }));

  expect(await screen.findByText("Job history linked to a processing request cannot be cleaned up")).toBeInTheDocument();
  expect(getRecordingJobs).toHaveBeenCalledOnce();
});
