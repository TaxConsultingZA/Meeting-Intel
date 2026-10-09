import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, getApprovedActionItems } from "@/lib/api";
import ActionItemsClient from "../action-items-client";

vi.mock("@/lib/api", () => ({ getApprovedActionItems: vi.fn(), ApiError: class extends Error { constructor(public status: number, public responseBody: string) { super(responseBody); } } }));
const page = {
  viewer_upn: "alice@example.test", has_more: false,
  items: [{ id: "a1", meeting_id: "m1", meeting_title: "Budget", task: "Send report", owner: "Alice", deadline_iso: "2026-10-12", deadline_text: "Monday", source_quote: "Please send the report." }],
};
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getApprovedActionItems).mockResolvedValue(page); });
afterEach(cleanup);

it("shows approved source fields, evidence and meeting link without write controls", async () => {
  render(<ActionItemsClient accessToken="token" />);
  expect(await screen.findByText("Send report")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Budget" })).toHaveAttribute("href", "/meetings/m1");
  expect(screen.getByText("Alice")).toBeInTheDocument();
  expect(screen.getByText("2026-10-12")).toBeInTheDocument();
  expect(screen.getByText("Please send the report.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^(save|edit|assign|start tracking)/i })).not.toBeInTheDocument();
  expect(getApprovedActionItems).toHaveBeenCalledWith("token", expect.objectContaining({ view: "mine" }), expect.any(AbortSignal));
});

it("switches views and applies all three filters", async () => {
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByText("Send report");
  fireEvent.click(screen.getByRole("button", { name: "All Accessible" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ view: "all" }), expect.anything()));
  fireEvent.change(screen.getByLabelText("Meeting"), { target: { value: "Budget" } });
  fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "Alice" } });
  fireEvent.change(screen.getByLabelText("Deadline"), { target: { value: "Monday" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", { view: "all", meeting: "Budget", owner: "Alice", deadline: "Monday", offset: 0 }, expect.anything()));
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", { view: "all", meeting: "", owner: "", deadline: "", offset: 0 }, expect.anything()));
});

it("paginates and resets the offset when views change", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue({ ...page, has_more: true });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByText("Send report");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 50 }), expect.anything()));
  await screen.findByText("Send report");
  fireEvent.click(screen.getByRole("button", { name: "All Accessible" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 0, view: "all" }), expect.anything()));
});

it("clears restricted data on a failed refresh and allows retry", async () => {
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByText("Send report");
  vi.mocked(getApprovedActionItems).mockRejectedValueOnce(new ApiError(403, "Access denied."));
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Access denied.");
  expect(screen.queryByText("Send report")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByText("Send report")).toBeInTheDocument();
});

it("shows empty and missing-value states", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValueOnce({ ...page, items: [] });
  render(<ActionItemsClient accessToken="token" />);
  expect(await screen.findByRole("heading", { name: "No actions found for you" })).toBeInTheDocument();
  vi.mocked(getApprovedActionItems).mockResolvedValueOnce({ ...page, items: [{ ...page.items[0], meeting_title: null, owner: null, deadline_iso: null, deadline_text: null, source_quote: null }] } as unknown as typeof page);
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByRole("link", { name: "Untitled meeting" })).toBeInTheDocument();
  expect(screen.getAllByText("Unspecified")).toHaveLength(2);
  expect(screen.getByText("No source evidence provided.")).toBeInTheDocument();
});

it("ignores an obsolete response after a view change", async () => {
  let resolveOld!: (value: typeof page) => void;
  vi.mocked(getApprovedActionItems).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
  render(<ActionItemsClient accessToken="token" />);
  fireEvent.click(screen.getByRole("button", { name: "All Accessible" }));
  await screen.findByText("Send report");
  resolveOld({ ...page, items: [{ ...page.items[0], task: "Obsolete task" }] });
  await waitFor(() => expect(screen.queryByText("Obsolete task")).not.toBeInTheDocument());
});

it("distinguishes my email matches from all-accessible empty results without extra requests", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue({ ...page, items: [] });
  render(<ActionItemsClient accessToken="token" />);
  expect(await screen.findByRole("heading", { name: "No actions found for you" })).toBeInTheDocument();
  expect(screen.getByText(/No approved actions list your account email/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  expect(getApprovedActionItems).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "View All Accessible" }));
  expect(await screen.findByRole("heading", { name: "No action items available" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View meetings on Dashboard" })).toHaveAttribute("href", "/");
  expect(getApprovedActionItems).toHaveBeenCalledTimes(2);
  expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", { view: "all", meeting: "", owner: "", deadline: "", offset: 0 }, expect.anything());
});

it("uses only applied filters to select the no-matches message", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue({ ...page, items: [] });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByRole("heading", { name: "No actions found for you" });
  fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "Alice" } });
  expect(screen.queryByRole("heading", { name: "No matching action items" })).not.toBeInTheDocument();
  expect(getApprovedActionItems).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  expect(await screen.findByRole("heading", { name: "No matching action items" })).toBeInTheDocument();
  expect(screen.getByText(/Try changing or clearing the filters above/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "View All Accessible" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(await screen.findByRole("heading", { name: "No actions found for you" })).toBeInTheDocument();
});

it("does not treat whitespace-only filters as applied restrictions", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue({ ...page, items: [] });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByRole("heading", { name: "No actions found for you" });
  fireEvent.change(screen.getByLabelText("Meeting"), { target: { value: "   " } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ meeting: "   " }), expect.anything()));
  expect(await screen.findByRole("heading", { name: "No actions found for you" })).toBeInTheDocument();
});

it("gives the selected view a clear highlight and explains action availability", async () => {
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByText("Send report");
  const mine = screen.getByRole("button", { name: "My Actions" });
  const all = screen.getByRole("button", { name: "All Accessible" });
  expect(mine).toHaveAttribute("aria-pressed", "true");
  expect(all).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByText(/Transcript-only meetings do not create action items/)).toBeInTheDocument();
  fireEvent.click(all);
  await screen.findByText("Send report");
  expect(all).toHaveAttribute("aria-pressed", "true");
  expect(mine).toHaveAttribute("aria-pressed", "false");
});

it("allows returning from an empty later page without displaying pagination", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValueOnce({ ...page, has_more: true }).mockResolvedValueOnce({ ...page, items: [] });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByText("Send report");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByRole("button", { name: "Return to first page" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "No actions on this page" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Return to first page" }));
  expect(await screen.findByText("Send report")).toBeInTheDocument();
  expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 0 }), expect.anything());
});
