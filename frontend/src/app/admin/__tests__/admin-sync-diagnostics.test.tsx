import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getAdminUserSyncStatus, getBusinessUnits, getRegisteredUsers } from "@/lib/api";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({
  decideMeetingEditAccess: vi.fn(), decideRecordingProcessing: vi.fn(), getAdminMeetings: vi.fn(),
  getAdminUserSyncStatus: vi.fn(), getBusinessUnits: vi.fn(), getRecordingJobs: vi.fn(), getRegisteredUsers: vi.fn(),
  registerUser: vi.fn(), removeUser: vi.fn(), reprocessRecordingJob: vi.fn(),
  revokeAdminMeetingAccess: vi.fn(), updateUser: vi.fn(),
}));
vi.mock("@/components/recording-jobs", () => ({ JobControls: () => null }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("loads compact per-user sync diagnostics only when requested", async () => {
  vi.mocked(getRegisteredUsers).mockResolvedValue([{
    upn: "member@example.test", display_name: "Member", business_unit_id: null,
    business_unit_name: null, is_admin: false, is_subscribed: true,
    subscribed_at: null, registered_at: "2026-09-15T00:00:00Z",
  }]);
  vi.mocked(getBusinessUnits).mockResolvedValue([]);
  vi.mocked(getAdminUserSyncStatus).mockResolvedValue([{
    source: "calendar", status: "success", last_attempted_at: "2026-09-15T01:00:00Z",
    last_succeeded_at: "2026-09-15T01:00:00Z", last_error: null,
  }]);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);

  expect(getAdminUserSyncStatus).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Users"));
  await screen.findByText("member@example.test");
  expect(getAdminUserSyncStatus).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Sync" }));

  await waitFor(() => expect(getAdminUserSyncStatus).toHaveBeenCalledWith("member@example.test", "token"));
  expect(await screen.findByText("Calendar")).toBeVisible();
  expect(screen.getByText("OneDrive")).toBeVisible();
  expect(screen.getByText("unavailable")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Sync" }));
  fireEvent.click(screen.getByRole("button", { name: "Sync" }));
  expect(getAdminUserSyncStatus).toHaveBeenCalledTimes(1);
});
