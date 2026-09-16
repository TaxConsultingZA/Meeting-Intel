import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getAdminMeetings, getBusinessUnits, getRecordingJobs, getRegisteredUsers } from "@/lib/api";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({
  decideMeetingEditAccess: vi.fn(), decideRecordingProcessing: vi.fn(), getAdminMeetings: vi.fn(),
  getAdminUserSyncStatus: vi.fn(), getBusinessUnits: vi.fn(), getRecordingJobs: vi.fn(), getRegisteredUsers: vi.fn(),
  registerUser: vi.fn(), removeUser: vi.fn(), reprocessRecordingJob: vi.fn(),
  revokeAdminMeetingAccess: vi.fn(), updateUser: vi.fn(),
}));
vi.mock("@/components/recording-jobs", () => ({ JobControls: () => null }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("keeps access requests open and lazily loads collapsed sections once", async () => {
  vi.mocked(getAdminMeetings).mockResolvedValue([]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  vi.mocked(getRegisteredUsers).mockResolvedValue([]);
  vi.mocked(getBusinessUnits).mockResolvedValue([]);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);

  expect(screen.getByText("No access requests.")).toBeVisible();
  expect(getAdminMeetings).not.toHaveBeenCalled();
  expect(getRecordingJobs).not.toHaveBeenCalled();
  expect(getRegisteredUsers).not.toHaveBeenCalled();

  fireEvent.click(screen.getByText("Meetings"));
  await waitFor(() => expect(getAdminMeetings).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByText(/Meetings/));
  fireEvent.click(screen.getByText(/Meetings/));
  await waitFor(() => expect(getAdminMeetings).toHaveBeenCalledTimes(1));

  fireEvent.click(screen.getByText("Users"));
  await waitFor(() => {
    expect(getRegisteredUsers).toHaveBeenCalledWith("token");
    expect(getBusinessUnits).toHaveBeenCalledWith("token");
  });
});
