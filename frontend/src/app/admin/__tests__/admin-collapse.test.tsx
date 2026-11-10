import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getAdminMeetings, getBusinessUnits, getRecordingJobs, getRegisteredUsers } from "@/lib/api";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({
  cleanupAdminJob: vi.fn(),
  decideMeetingEditAccess: vi.fn(), decideRecordingProcessing: vi.fn(), getAdminMeetings: vi.fn(), getAuditEvents: vi.fn().mockResolvedValue({items: []}),
  getAdminUserSyncStatus: vi.fn(), getBusinessUnits: vi.fn(), getRecordingJobs: vi.fn(), getRegisteredUsers: vi.fn(),
  registerUser: vi.fn(), removeUser: vi.fn(), reprocessRecordingJob: vi.fn(),
  revokeAdminMeetingAccess: vi.fn(), updateUser: vi.fn(),
}));
vi.mock("@/components/recording-jobs", () => ({ JobControls: () => null }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("loads the unified records workspace and loads Users without a collapse control", async () => {
  vi.mocked(getAdminMeetings).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  vi.mocked(getRegisteredUsers).mockResolvedValue([]);
  vi.mocked(getBusinessUnits).mockResolvedValue([]);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);
  await screen.findByText("No matching records in the loaded range.");
  expect(screen.getByRole("heading", {name: "Access Requests"})).toBeVisible();
  expect(getAdminMeetings).toHaveBeenCalledOnce();
  expect(getRecordingJobs).toHaveBeenCalledOnce();
  expect(screen.getByRole("heading", {name: /^Users/})).toBeVisible();
  expect(screen.queryByRole("button", {name: /^Users/})).not.toBeInTheDocument();
  await waitFor(() => expect(getRegisteredUsers).toHaveBeenCalledWith("token"));
});
