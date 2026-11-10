import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { decideRecordingProcessing } from "@/lib/api";
import type { AdminAccessRequest } from "@/lib/types";
import AdminClient from "../admin-client";

vi.mock("@/lib/api", () => ({
  cleanupAdminJob: vi.fn(),
  decideMeetingEditAccess: vi.fn(), decideRecordingProcessing: vi.fn(), getAdminMeetings: vi.fn().mockResolvedValue([]), getAuditEvents: vi.fn().mockResolvedValue({items: []}),
  getAdminUserSyncStatus: vi.fn(), getBusinessUnits: vi.fn().mockResolvedValue([]), getRecordingJobs: vi.fn().mockResolvedValue([]), getRegisteredUsers: vi.fn().mockResolvedValue([]),
  registerUser: vi.fn(), removeUser: vi.fn(), reprocessRecordingJob: vi.fn(),
  revokeAdminMeetingAccess: vi.fn(), updateUser: vi.fn(),
}));
vi.mock("@/components/recording-jobs", () => ({ JobControls: () => null }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function processing(overrides: Partial<AdminAccessRequest> = {}): AdminAccessRequest {
  return {
    id: "request-1", meeting_id: null, meeting: "Project Review",
    requester_upn: "requester@example.test", requester_name: "Requester",
    owner_upn: "owner@example.test", organizer_upn: "organizer@example.test",
    request_type: "processing", status: "pending", requested_at: "2026-09-15T00:00:00Z",
    can_approve: true, ...overrides,
  };
}

it("keeps record search and access requests in the unified Admin workspace", () => {
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="token" />);
  expect(screen.getByRole("heading", {name: "Find a record"})).toBeVisible();
  expect(screen.getByRole("heading", {name: "Access Requests"})).toBeVisible();
});

it("confirms and decides only pending processing requests", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(decideRecordingProcessing).mockResolvedValue({} as never);
  render(<AdminClient initialRequests={[
      processing(),
      processing({ id: "processed", meeting: "Existing result", can_approve: false }),
      processing({ id: "approved", meeting: "Approved request", status: "approved", can_approve: false }),
      processing({ id: "rejected", meeting: "Rejected request", status: "denied", can_approve: false }),
    ]} callerUpn="admin@example.test" accessToken="token" />);

  expect(screen.getAllByRole("button", { name: "Approve" }).filter(button => !button.hasAttribute("disabled"))).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: "Reject" })).toHaveLength(2);
  fireEvent.click(screen.getAllByRole("button", { name: "Approve" }).find(button => !button.hasAttribute("disabled"))!);

  expect(confirm).toHaveBeenCalledWith("Approve processing request for Project Review?");
  await waitFor(() => expect(decideRecordingProcessing).toHaveBeenCalledWith("request-1", true, "token"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled());
  expect(screen.getAllByRole("button", { name: "Reject" })).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Reject" }));
  expect(confirm).toHaveBeenCalledWith("Reject processing request for Existing result?");
  await waitFor(() => expect(decideRecordingProcessing).toHaveBeenCalledWith("processed", false, "token"));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument());
});
