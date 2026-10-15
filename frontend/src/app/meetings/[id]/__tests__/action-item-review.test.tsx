import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ActionItemReview from "../action-item-review";
import { editActionItem } from "@/lib/api";
import type { ActionItemOut } from "@/lib/types";

vi.mock("@/lib/api", () => ({ editActionItem: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const item: ActionItemOut = { id: "a1", task: "Send report", owner: "Alice", deadline_iso: "2026-10-12", deadline_text: "Monday", confidence: "high", source_quote: "Send report", approved: false };
function setup(action = item, canEdit = true, transcript: string | null = "[Speaker A] Please Send report tomorrow.") {
  const onUpdate = vi.fn();
  render(<ActionItemReview items={[action]} accessToken="token" canEdit={canEdit} transcript={transcript} onUpdate={onUpdate} />);
  return onUpdate;
}
function edit() { fireEvent.click(screen.getByRole("button", { name: /Edit action item:/ })); }

it("reports open editors and clears their approval block when removed", () => {
  const onEditingChange = vi.fn();
  const view = render(<ActionItemReview items={[item]} accessToken="token" canEdit onUpdate={vi.fn()} onEditingChange={onEditingChange} />);
  edit();
  expect(onEditingChange).toHaveBeenLastCalledWith(item.id, true);
  view.rerender(<ActionItemReview items={[]} accessToken="token" canEdit onUpdate={vi.fn()} onEditingChange={onEditingChange} />);
  expect(onEditingChange).toHaveBeenLastCalledWith(item.id, false);
});

it("flags missing details and low confidence without changing results", () => {
  setup({ ...item, owner: null, deadline_iso: null, deadline_text: null, confidence: "low" });
  expect(screen.getByText(/1 with review flags/)).toBeInTheDocument();
  expect(screen.getByText("Requires review")).toBeInTheDocument();
  expect(screen.getAllByText("Missing owner")).toHaveLength(2);
  expect(screen.getAllByText("Missing due date")).toHaveLength(2);
  expect(screen.getByText("Low confidence")).toBeInTheDocument();
  expect(editActionItem).not.toHaveBeenCalled();
});

it("saves all four fields through the existing partial update contract", async () => {
  vi.mocked(editActionItem).mockResolvedValue(undefined);
  const updated = setup(); edit();
  fireEvent.change(screen.getByLabelText("Task (required)"), { target: { value: "  Send final report  " } });
  fireEvent.change(screen.getByLabelText("Owner"), { target: { value: " Bob " } });
  fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2026-10-15" } });
  fireEvent.change(screen.getByLabelText("Confidence"), { target: { value: "medium" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(updated).toHaveBeenCalledWith({ ...item, task: "Send final report", owner: "Bob", deadline_iso: "2026-10-15", confidence: "medium" }));
  expect(editActionItem).toHaveBeenCalledWith("a1", { task: "Send final report", owner: "Bob", deadline_iso: "2026-10-15", confidence: "medium" }, "token");
});

it("rejects blank tasks and accidental clearing of populated fields", () => {
  setup(); edit();
  for (const label of ["Task (required)", "Owner", "Due date"]) fireEvent.change(screen.getByLabelText(label), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(screen.getAllByRole("alert")).toHaveLength(3);
  expect(screen.getByLabelText("Task (required)")).toHaveAttribute("aria-invalid", "true");
  expect(editActionItem).not.toHaveBeenCalled();
});

it("allows absent optional values to remain absent and sends only changed fields", async () => {
  vi.mocked(editActionItem).mockResolvedValue(undefined);
  setup({ ...item, owner: null, deadline_iso: null }); edit();
  fireEvent.change(screen.getByLabelText("Task (required)"), { target: { value: "Check report" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(editActionItem).toHaveBeenCalledWith("a1", { task: "Check report" }, "token"));
});

it("cancel discards drafts and reopening starts with saved values", () => {
  setup(); edit();
  fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "Bob" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" })); edit();
  expect(screen.getByLabelText("Owner")).toHaveValue("Alice");
  expect(editActionItem).not.toHaveBeenCalled();
});

it("retains drafts on failure, disables cancellation during save, and prevents duplicate requests", async () => {
  let reject!: (reason: Error) => void;
  vi.mocked(editActionItem).mockReturnValue(new Promise((_, fail) => { reject = fail; }));
  setup(); edit();
  fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "Bob" } });
  fireEvent.submit(screen.getByRole("form")); fireEvent.submit(screen.getByRole("form"));
  expect(editActionItem).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByLabelText("Owner")).toBeDisabled();
  reject(new Error("provider secret"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Your edits are kept");
  expect(screen.getByLabelText("Owner")).toHaveValue("Bob");
});

it("exposes source quote and matching transcript context", () => {
  setup(); fireEvent.click(screen.getByText("View source evidence"));
  expect(screen.getByText("Extracted source quote")).toBeInTheDocument();
  expect(screen.getByText(/first exact text match/)).toBeInTheDocument();
  expect(screen.getByText(/\[Speaker A\]/)).toBeInTheDocument();
});

it.each([null, "Changed transcript"])("explains unavailable or unmatched transcript evidence: %s", transcript => {
  setup(item, false, transcript);
  expect(screen.queryByRole("button", { name: /Edit action item:/ })).not.toBeInTheDocument();
  expect(screen.getByText(transcript ? /No exact match/ : /Transcript unavailable/)).toBeInTheDocument();
});

it("shows an explicit missing evidence message", () => {
  setup({ ...item, source_quote: null });
  expect(screen.getByText("No source evidence provided.")).toBeInTheDocument();
});

it("preserves the spoken deadline beside the resolved due date", () => {
  setup();
  expect(screen.getByRole("columnheader", { name: "Due date" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Owner" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Confidence" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Source evidence" })).toBeInTheDocument();
  expect(screen.getByText("2026-10-12")).toBeInTheDocument();
  expect(screen.getByText("Original wording: Monday")).toBeInTheDocument();
  expect(screen.queryByText("Due date not resolved")).not.toBeInTheDocument();
});

it.each(["Friday", "next week"])("does not imply a resolved date for %s", deadline_text => {
  setup({ ...item, deadline_iso: null, deadline_text });
  expect(screen.getByText("Due date not resolved")).toBeInTheDocument();
  expect(screen.getByText(`Original wording: ${deadline_text}`)).toBeInTheDocument();
  expect(screen.getByText(/original meeting, not today/)).toBeInTheDocument();
});
