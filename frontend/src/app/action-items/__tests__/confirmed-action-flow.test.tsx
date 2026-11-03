import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getApprovedActionItems, setTaskCompletion } from "@/lib/api";
import type { ApprovedActionItemsPage, TaskCompletion } from "@/lib/types";
import fixture from "@/test/fixtures/confirmed-action-flow.json";
import ActionItemsClient from "../action-items-client";

// These responses were produced by the real synthetic confirmation/list/
// completion APIs in check_confirmed_actions_integration.py, not hand-written.
const flow = fixture as unknown as Record<string, ApprovedActionItemsPage> & {
  complete_response: TaskCompletion; reopen_response: TaskCompletion;
};
vi.mock("@/lib/api", () => ({ getApprovedActionItems: vi.fn(), setTaskCompletion: vi.fn(), ApiError: class extends Error {} }));
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers(); });

it("renders a human-confirmed action with pending notes, removes its reminder on completion and restores on reopen", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 3, 12));
  vi.mocked(getApprovedActionItems).mockResolvedValueOnce(flow.pending).mockResolvedValueOnce(flow.confirmed).mockResolvedValueOnce(flow.revoked);
  vi.mocked(setTaskCompletion).mockResolvedValueOnce(flow.complete_response).mockResolvedValueOnce(flow.reopen_response);
  render(<ActionItemsClient accessToken="synthetic-token" />);
  await screen.findByRole("heading", { name: "No confirmed action items yet" });
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  const reminders = await screen.findByLabelText("Personal action item due reminders");
  expect(within(reminders).getByText(/Prepare report/)).toBeVisible();
  expect(screen.getByText(/while meeting notes remain awaiting review/)).toBeVisible();
  expect(screen.queryByText("Archive evidence")).not.toBeInTheDocument();
  expect(screen.queryByText("Check totals")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Mark complete: Prepare report" }));
  await waitFor(() => expect(screen.queryByLabelText("Personal action item due reminders")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Reopen: Prepare report" }));
  await screen.findByLabelText("Personal action item due reminders");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByRole("heading", { name: "No confirmed action items yet" });
  expect(screen.queryByText(/Prepare report/)).not.toBeInTheDocument();
  expect(setTaskCompletion).toHaveBeenNthCalledWith(1, flow.confirmed.items[0].id, true, "synthetic-token");
  expect(setTaskCompletion).toHaveBeenNthCalledWith(2, flow.confirmed.items[0].id, false, "synthetic-token");
});

it("retains the reminder after a failed completion and recovers on retry", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 3, 12));
  vi.mocked(getApprovedActionItems).mockResolvedValue(flow.confirmed);
  vi.mocked(setTaskCompletion).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(flow.complete_response);
  render(<ActionItemsClient accessToken="synthetic-token" />);
  await screen.findByLabelText("Personal action item due reminders");
  fireEvent.click(screen.getByRole("button", { name: "Mark complete: Prepare report" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Personal action item due reminders")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Mark complete: Prepare report" }));
  await waitFor(() => expect(screen.queryByLabelText("Personal action item due reminders")).not.toBeInTheDocument());
});

it("clears the previous identity's tasks before a new identity finishes authorization", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValueOnce(flow.confirmed).mockReturnValueOnce(new Promise(() => {}));
  const { rerender } = render(<ActionItemsClient accessToken="alice" />);
  await screen.findByRole("button", { name: "Mark complete: Prepare report" });
  rerender(<ActionItemsClient accessToken="another-user" />);
  expect(screen.queryByText(/Prepare report/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Personal action item due reminders")).not.toBeInTheDocument();
});
