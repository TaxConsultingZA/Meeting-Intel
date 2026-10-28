import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getMeetingDecisions, saveMeetingDecisions } from "@/lib/api";
import MeetingDecisions from "../meeting-decisions";

vi.mock("@/lib/api", () => ({ getMeetingDecisions: vi.fn(), saveMeetingDecisions: vi.fn() }));
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
