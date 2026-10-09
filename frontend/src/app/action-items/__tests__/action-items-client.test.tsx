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
  expect(getApprovedActionItems).toHaveBeenCalledWith("token", expect.objectContaining({ view: "all" }), expect.any(AbortSignal));
});

it("applies and clears all three filters within accessible meetings", async () => {
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByText("Send report");
  fireEvent.change(screen.getByLabelText("Meeting"), { target: { value: "Budget" } });
  fireEvent.change(screen.getByLabelText("Person mentioned in meeting"), { target: { value: "Alice" } });
  fireEvent.change(screen.getByLabelText("Deadline mentioned"), { target: { value: "Monday" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", { view: "all", meeting: "Budget", owner: "Alice", deadline: "Monday", offset: 0 }, expect.anything()));
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", { view: "all", meeting: "", owner: "", deadline: "", offset: 0 }, expect.anything()));
});

it("paginates and resets the offset when filters change", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue({ ...page, has_more: true });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByText("Send report");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 50 }), expect.anything()));
  await screen.findByText("Send report");
  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 0, view: "all" }), expect.anything()));
  await screen.findByText("Send report");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 50 }), expect.anything()));
  await screen.findByText("Send report");
  fireEvent.change(screen.getByLabelText("Meeting"), { target: { value: "Budget" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ offset: 0, view: "all", meeting: "Budget" }), expect.anything()));
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
  expect(await screen.findByRole("heading", { name: "No approved action items yet" })).toBeInTheDocument();
  vi.mocked(getApprovedActionItems).mockResolvedValueOnce({ ...page, items: [{ ...page.items[0], meeting_title: null, owner: null, deadline_iso: null, deadline_text: null, source_quote: null }] } as unknown as typeof page);
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByRole("link", { name: "Untitled meeting" })).toBeInTheDocument();
  expect(screen.getAllByText("Unspecified")).toHaveLength(2);
  expect(screen.getByText("No source evidence provided.")).toBeInTheDocument();
});

it("ignores an obsolete response after a filter change", async () => {
  let resolveOld!: (value: typeof page) => void;
  vi.mocked(getApprovedActionItems).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
  render(<ActionItemsClient accessToken="token" />);
  fireEvent.change(screen.getByLabelText("Meeting"), { target: { value: "Budget" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await screen.findByText("Send report");
  resolveOld({ ...page, items: [{ ...page.items[0], task: "Obsolete task" }] });
  await waitFor(() => expect(screen.queryByText("Obsolete task")).not.toBeInTheDocument());
});

it("explains approval availability and links to meetings without extra requests", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue({ ...page, items: [] });
  render(<ActionItemsClient accessToken="token" />);
  expect(await screen.findByRole("heading", { name: "No approved action items yet" })).toBeInTheDocument();
  expect(screen.getByText(/Action items appear here after meeting notes containing extracted action items are approved/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  expect(getApprovedActionItems).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("link", { name: "View meetings on Dashboard" })).toHaveAttribute("href", "/");
  expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", { view: "all", meeting: "", owner: "", deadline: "", offset: 0 }, expect.anything());
});

it("uses only applied filters to select the no-matches message", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue({ ...page, items: [] });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByRole("heading", { name: "No approved action items yet" });
  fireEvent.change(screen.getByLabelText("Person mentioned in meeting"), { target: { value: "Alice" } });
  expect(screen.queryByRole("heading", { name: "No matching action items" })).not.toBeInTheDocument();
  expect(getApprovedActionItems).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  expect(await screen.findByRole("heading", { name: "No matching action items" })).toBeInTheDocument();
  expect(screen.getByText(/Try changing or clearing the filters above/)).toBeInTheDocument();
  expect(screen.getByText(/No approved action items from meetings you can access match your applied filters/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "View meetings on Dashboard" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(await screen.findByRole("heading", { name: "No approved action items yet" })).toBeInTheDocument();
});

it("does not treat whitespace-only filters as applied restrictions", async () => {
  vi.mocked(getApprovedActionItems).mockResolvedValue({ ...page, items: [] });
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByRole("heading", { name: "No approved action items yet" });
  fireEvent.change(screen.getByLabelText("Meeting"), { target: { value: "   " } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await waitFor(() => expect(getApprovedActionItems).toHaveBeenLastCalledWith("token", expect.objectContaining({ meeting: "   " }), expect.anything()));
  expect(await screen.findByRole("heading", { name: "No approved action items yet" })).toBeInTheDocument();
});

it("explains meeting outputs with neutral labels and no personal action views", async () => {
  render(<ActionItemsClient accessToken="token" />);
  await screen.findByText("Send report");
  expect(screen.getByText("Approved action items from meetings you can access. Review and edit extracted action items in Meeting Detail before approval.")).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Action item views" })).not.toBeInTheDocument();
  expect(screen.queryByText(/My Actions|All Accessible|account email/)).not.toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Person mentioned in meeting" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Deadline mentioned" })).toBeInTheDocument();
  expect(screen.getByLabelText("Person mentioned in meeting")).toBeInTheDocument();
  expect(screen.getByLabelText("Deadline mentioned")).toBeInTheDocument();
  expect(screen.queryByRole("columnheader", { name: "Owner" })).not.toBeInTheDocument();
  expect(screen.queryByRole("columnheader", { name: "Deadline" })).not.toBeInTheDocument();
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
