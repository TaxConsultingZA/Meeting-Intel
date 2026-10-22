import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getRecordingJobs } from "@/lib/api";
import type { RecordingJobOut } from "@/lib/types";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({ getRecordingJobs: vi.fn() }));
// Invoke only the existing read callback; never perform a job mutation.
vi.mock("@/components/recording-jobs", () => ({
  recordingStatusMessage: () => "Safe failure category.",
  JobControls: ({ onChanged }: { onChanged: () => Promise<void> }) =>
    <button onClick={() => void onChanged().catch(() => {})}>Reload job snapshot</button>,
}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const job: RecordingJobOut = {
  job_id: "j1", drive_item_id: "d1", meeting_id: null, title: "Recording",
  status: "failed", processing_status: "failed", phase: "failed", review_status: null,
  attempts: 1, max_attempts: 3, error: null, can_retry: false, can_cancel: false,
  can_reprocess: false, processing_enabled: false,
};

it("invalidates the loaded statistics on a failed refresh and permits a read-only retry", async () => {
  vi.mocked(getRecordingJobs).mockResolvedValueOnce([job]);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);
  fireEvent.click(screen.getByText("Processing Jobs"));
  await screen.findByRole("region", { name: "Processing job statistics" });
  let reject!: (error: Error) => void;
  vi.mocked(getRecordingJobs).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
  fireEvent.click(screen.getByRole("button", { name: "Reload job snapshot" }));
  expect(screen.queryByRole("region", { name: "Processing job statistics" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Failed recordings" })).not.toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Recording jobs loading" })).toBeVisible();
  reject(new Error("secret upstream transcript"));
  expect(await screen.findByText(/Recording jobs could not be loaded/)).toBeVisible();
  expect(screen.queryByRole("region", { name: "Processing job statistics" })).not.toBeInTheDocument();
  expect(screen.queryByText(/secret upstream/)).not.toBeInTheDocument();
  vi.mocked(getRecordingJobs).mockResolvedValueOnce([]);
  fireEvent.click(screen.getByText("Processing Jobs"));
  fireEvent.click(screen.getByText("Processing Jobs"));
  await screen.findByText("Failed recordings (0)");
  expect(getRecordingJobs).toHaveBeenCalledTimes(3);
});
