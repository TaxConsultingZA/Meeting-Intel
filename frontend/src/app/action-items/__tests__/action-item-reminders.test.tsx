import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getApprovedActionItems, setTaskCompletion } from "@/lib/api";
import ActionItemsClient from "../action-items-client";

vi.mock("@/lib/api", () => ({
  getApprovedActionItems: vi.fn(), setTaskCompletion: vi.fn(),
  ApiError: class extends Error {},
}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const page = {
  viewer_upn: "alice@example.test", has_more: false,
  items: [{ id: "a", meeting_id: "m", meeting_title: "Meeting", task: "Send report",
    owner: "alice@example.test", deadline_iso: "2020-01-01", deadline_text: null,
    source_quote: null, can_complete: true }],
};

it("hides previous reminders while loading and after a list failure, then restores on retry", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue(page);
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByLabelText("Personal action item due reminders");
  let reject!: (error: Error) => void;
  vi.mocked(getApprovedActionItems).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(screen.queryByLabelText("Personal action item due reminders")).not.toBeInTheDocument();
  reject(new Error("offline"));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("Personal action item due reminders")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByLabelText("Personal action item due reminders");
});

it("updates reminders after Complete and Reopen without reloading the list", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue(page);
  vi.mocked(setTaskCompletion).mockResolvedValueOnce({ completed_at: "2026-10-22T00:00:00Z", can_complete: true })
    .mockResolvedValueOnce({ completed_at: null, can_complete: true });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByLabelText("Personal action item due reminders");
  fireEvent.click(screen.getByRole("button", { name: "Mark complete: Send report" }));
  await waitFor(() => expect(screen.queryByLabelText("Personal action item due reminders")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Reopen: Send report" }));
  await screen.findByLabelText("Personal action item due reminders");
  expect(getApprovedActionItems).toHaveBeenCalledTimes(1);
});

it("replaces reminders with the requested page and applied filter results", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValueOnce({ ...page, has_more: true });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByLabelText("Personal action item due reminders");
  let resolve!: (value: typeof page) => void;
  vi.mocked(getApprovedActionItems).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.queryByLabelText("Personal action item due reminders")).not.toBeInTheDocument();
  expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 50 }), expect.any(AbortSignal));
  resolve({ ...page, items: [{ ...page.items[0], id: "b", task: "Second page task" }] });
  const reminders = await screen.findByLabelText("Personal action item due reminders");
  expect(within(reminders).getByText(/Second page task/)).toBeVisible();
  expect(within(reminders).queryByText(/Send report/)).not.toBeInTheDocument();
  vi.mocked(getApprovedActionItems).mockResolvedValueOnce({ ...page, items: [] });
  fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "Bob" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await screen.findByText("No matching action items");
  expect(screen.queryByLabelText("Personal action item due reminders")).not.toBeInTheDocument();
  expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 0, owner: "Bob" }), expect.any(AbortSignal));
});
