import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getAdminMeetings, getBusinessUnits, getRecordingJobs, getRegisteredUsers } from "@/lib/api";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({
  cleanupAdminJob: vi.fn(),
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

it("keeps concurrent sections loading independently and avoids duplicate in-flight reads", async () => {
  let finish!: (rows: never[]) => void;
  vi.mocked(getAdminMeetings).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);
  fireEvent.click(screen.getByText("Meetings"));
  await screen.findByRole("status", { name: "Meetings loading" });
  fireEvent.click(screen.getByText("Processing Jobs"));
  await screen.findByText(/No recording jobs yet/);
  expect(screen.getByRole("status", { name: "Meetings loading" })).toBeVisible();
  fireEvent.click(screen.getByText("Meetings"));
  fireEvent.click(screen.getByText("Meetings"));
  await act(async () => {});
  expect(getAdminMeetings).toHaveBeenCalledOnce();
  await act(async () => { finish([]); });
  expect(screen.queryByRole("status", { name: "Meetings loading" })).not.toBeInTheDocument();
});
