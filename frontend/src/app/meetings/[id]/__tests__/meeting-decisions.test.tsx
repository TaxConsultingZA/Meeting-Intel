import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError, getMeetingDecisions, saveMeetingDecisions } from "@/lib/api";
import MeetingDecisions from "../meeting-decisions";

vi.mock("@/lib/api", () => ({ ApiError: class extends Error { status: number; constructor(status: number) { super(); this.status = status; } }, getMeetingDecisions: vi.fn(), saveMeetingDecisions: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const row = { id: "d1", meeting_id: "m1", content: "Approve budget", decision_date: "2026-10-22" };
const props = { meetingId: "m1", meetingTitle: "Budget meeting", token: "token", canEdit: true,
  onPendingChange: vi.fn(), onSaved: vi.fn() };

it("loads empty decisions, saves human-entered content and date, then permits review edits", async () => {
  vi.mocked(getMeetingDecisions).mockResolvedValue([]);
  vi.mocked(saveMeetingDecisions).mockResolvedValueOnce([row]).mockResolvedValueOnce([{ ...row, content: "Revised budget" }]);
  render(<MeetingDecisions {...props} />);
  expect(await screen.findByText("No decisions recorded.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Edit decisions" }));
  expect(props.onPendingChange).toHaveBeenLastCalledWith(true);
  fireEvent.change(screen.getByLabelText("Decision 1 content"), { target: { value: "Approve budget" } });
  fireEvent.change(screen.getByLabelText("Decision 1 date"), { target: { value: "2026-10-22" } });
  fireEvent.submit(screen.getByRole("form", { name: "Edit meeting decisions" }));
  await screen.findByText("Approve budget");
  expect(saveMeetingDecisions).toHaveBeenLastCalledWith("m1", [{ content: "Approve budget", decision_date: "2026-10-22" }], "token");
  expect(screen.getByRole("link", { name: "Budget meeting" })).toHaveAttribute("href", "/meetings/m1");
  fireEvent.click(screen.getByRole("button", { name: "Edit decisions" }));
  fireEvent.change(screen.getByLabelText("Decision 1 content"), { target: { value: "Revised budget" } });
  fireEvent.submit(screen.getByRole("form", { name: "Edit meeting decisions" }));
  await screen.findByText("Revised budget");
  expect(props.onPendingChange).toHaveBeenLastCalledWith(false);
  expect(props.onSaved).toHaveBeenCalledTimes(2);
});

it("shows approved or viewer decisions as read-only without inferring participants", async () => {
  vi.mocked(getMeetingDecisions).mockResolvedValue([row]);
  render(<MeetingDecisions {...props} canEdit={false} />);
  await screen.findByText("Approve budget");
  expect(screen.queryByRole("button", { name: "Edit decisions" })).not.toBeInTheDocument();
  expect(screen.getByText(/Participants are not inferred/)).toBeVisible();
});

it("shows loading and safe errors, retries reads, and retains a failed-save draft", async () => {
  let reject!: (error: Error) => void;
  vi.mocked(getMeetingDecisions).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; })).mockResolvedValueOnce([row]);
  render(<MeetingDecisions {...props} />);
  expect(screen.getByRole("status", { name: "Decisions loading" })).toBeInTheDocument();
  reject(new Error("secret transcript"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Decisions could not be loaded.");
  expect(screen.queryByText("No decisions recorded.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reload decisions" }));
  await screen.findByText("Approve budget");
  fireEvent.click(screen.getByRole("button", { name: "Edit decisions" }));
  fireEvent.change(screen.getByLabelText("Decision 1 content"), { target: { value: "Unsaved changes" } });
  vi.mocked(saveMeetingDecisions).mockRejectedValueOnce(new Error("secret key"));
  fireEvent.submit(screen.getByRole("form", { name: "Edit meeting decisions" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Decisions could not be saved."));
  expect(screen.getByLabelText("Decision 1 content")).toHaveValue("Unsaved changes");
  expect(screen.queryByText(/secret transcript|secret key/)).not.toBeInTheDocument();
});

it("rejects whitespace content with recoverable validation feedback before sending a save", async () => {
  vi.mocked(getMeetingDecisions).mockResolvedValue([row]);
  render(<MeetingDecisions {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit decisions" }));
  fireEvent.change(screen.getByLabelText("Decision 1 content"), { target: { value: "   " } });
  fireEvent.submit(screen.getByRole("form", { name: "Edit meeting decisions" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Decision 1 needs content and a valid date.");
  expect(saveMeetingDecisions).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Decision 1 content")).toHaveValue("   ");
});


it("stays editing after clicking and a background read cannot clear pending draft state", async () => {
  vi.mocked(getMeetingDecisions).mockResolvedValue([row]);
  const view = render(<MeetingDecisions {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit decisions" }));
  expect(screen.getByRole("form", { name: "Edit meeting decisions" })).toBeVisible();
  let resolve!: (rows: typeof row[]) => void;
  vi.mocked(getMeetingDecisions).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  view.rerender(<MeetingDecisions {...props} token="renewed-token" />);
  fireEvent.change(screen.getByLabelText("Decision 1 content"), { target: { value: "Local draft" } });
  await act(async () => resolve([{ ...row, content: "Server background change" }]));
  expect(screen.getByLabelText("Decision 1 content")).toHaveValue("Local draft");
  expect(props.onPendingChange).toHaveBeenLastCalledWith(true);
});

it("keeps the draft on a failed background read and permits retry then save", async () => {
  vi.mocked(getMeetingDecisions).mockResolvedValueOnce([row]).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([row]);
  vi.mocked(saveMeetingDecisions).mockResolvedValue([row]);
  const view = render(<MeetingDecisions {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit decisions" }));
  fireEvent.change(screen.getByLabelText("Decision 1 content"), { target: { value: "Local draft" } });
  view.rerender(<MeetingDecisions {...props} token="renewed-token" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Any unsaved draft is kept");
  expect(screen.getByLabelText("Decision 1 content")).toHaveValue("Local draft");
  expect(screen.getByRole("button", { name: "Save decisions" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reload decisions" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save decisions" })).toBeEnabled());
  fireEvent.submit(screen.getByRole("form", { name: "Edit meeting decisions" }));
  expect(await screen.findByText("Decisions saved.")).toBeVisible();
  expect(screen.queryByRole("form")).not.toBeInTheDocument();
});

it.each(["permission", "meeting"])("retains and locks the draft with explicit %s feedback", async reason => {
  vi.mocked(getMeetingDecisions).mockResolvedValue([row]);
  const view = render(<MeetingDecisions {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit decisions" }));
  fireEvent.change(screen.getByLabelText("Decision 1 content"), { target: { value: "Keep me" } });
  view.rerender(<MeetingDecisions {...props} canEdit={reason !== "permission"} meetingId={reason === "meeting" ? "m2" : "m1"} />);
  expect(screen.getByRole("alert")).toHaveTextContent(reason === "meeting" ? "Meeting changed" : "Edit access is no longer available");
  expect(screen.getByLabelText("Decision 1 content")).toHaveValue("Keep me");
  expect(screen.getByRole("button", { name: "Save decisions" })).toBeDisabled();
  fireEvent.submit(screen.getByRole("form", { name: "Edit meeting decisions" }));
  expect(saveMeetingDecisions).not.toHaveBeenCalled();
});


it.each([401, 403])("retains a draft and explains access uncertainty after HTTP %s", async status => {
  vi.mocked(getMeetingDecisions).mockResolvedValueOnce([row]).mockRejectedValueOnce(new ApiError(status, "private detail"));
  const view = render(<MeetingDecisions {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit decisions" }));
  fireEvent.change(screen.getByLabelText("Decision 1 content"), { target: { value: "Access draft" } });
  view.rerender(<MeetingDecisions {...props} token="changed-session" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Your session expired or access was removed");
  expect(screen.getByLabelText("Decision 1 content")).toHaveValue("Access draft");
  expect(screen.getByRole("button", {name: "Save decisions"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "Cancel"}));
  expect(props.onPendingChange).toHaveBeenLastCalledWith(true);
});
