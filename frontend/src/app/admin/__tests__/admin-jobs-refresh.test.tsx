import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getRecordingJobs } from "@/lib/api";
import type { RecordingJobOut } from "@/lib/types";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({ getRecordingJobs: vi.fn(), getRegisteredUsers: vi.fn().mockResolvedValue([]), getBusinessUnits: vi.fn().mockResolvedValue([]), getAdminMeetings: vi.fn().mockResolvedValue([]), getAuditEvents: vi.fn().mockResolvedValue({items: []}) }));
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

it("keeps failed reads distinct from empty results and retries the unified query", async () => {
  vi.mocked(getRecordingJobs).mockRejectedValueOnce(new Error("secret upstream transcript")).mockResolvedValueOnce([job]);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);
  expect(await screen.findByText("Records could not be loaded. Please retry.")).toBeVisible();
  expect(screen.queryByText("No matching records in the loaded range.")).toBeNull();
  expect(screen.queryByText(/secret upstream/)).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "Retry"}));
  expect(await screen.findByText("Recording")).toBeVisible();
});
