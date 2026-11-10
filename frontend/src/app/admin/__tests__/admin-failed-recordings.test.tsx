import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getRecordingJobs } from "@/lib/api";
import type { RecordingJobOut } from "@/lib/types";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({
  cleanupAdminJob: vi.fn(), decideMeetingEditAccess: vi.fn(), decideRecordingProcessing: vi.fn(),
  getAdminMeetings: vi.fn().mockResolvedValue([]), getAuditEvents: vi.fn().mockResolvedValue({items: []}), getAdminUserSyncStatus: vi.fn(), getBusinessUnits: vi.fn().mockResolvedValue([]),
  getRecordingJobs: vi.fn(), getRegisteredUsers: vi.fn().mockResolvedValue([]), registerUser: vi.fn(), removeUser: vi.fn(),
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
it("shows safe failure evidence in unified recording Details", async () => {
  vi.mocked(getRecordingJobs).mockResolvedValue([job()]);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);
  const row = (await screen.findByText("Team meeting")).closest("article")!;
  fireEvent.click(within(row).getByRole("button", {name: "Details"}));
  expect(await screen.findByText("Failure: transcription · timeout")).toBeVisible();
  expect(screen.queryByText(/secret-token|raw transcript|private.example/)).toBeNull();
});
