import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, getAuditEvents } from "@/lib/api";
import type { AuditEvent, AuditEventsPage } from "@/lib/types";
import AuditLogsClient, { parseAuditDate } from "../audit-logs-client";
import { OutcomeBadge, safeMetadata } from "../audit-display";

vi.mock("@/lib/api", async (original) => ({ ...await original<typeof import("@/lib/api")>(), getAuditEvents: vi.fn() }));

const event: AuditEvent = {
  id: "00000000-0000-0000-0000-000000000001", occurred_at: "2026-10-06T10:00:00Z",
  event_type: "recording.processing", outcome: "failed", actor_type: "system",
  actor_id: "recording_worker", actor_upn: null, resource_type: "recording_job",
  resource_id: "00000000-0000-0000-0000-000000000002", job_id: null, meeting_id: null,
  correlation_id: "00000000-0000-0000-0000-000000000003",
  metadata: { attempt: 1, retry_scheduled: true, error_category: "processing_error" },
};
function page(items: AuditEvent[] = [event], next_cursor: string | null = null): AuditEventsPage {
  return { items, next_cursor, has_more: !!next_cursor, window_start: "2026-10-01T00:00:00Z", window_end: "2026-10-07T00:00:00Z" };
}
beforeEach(() => { vi.mocked(getAuditEvents).mockResolvedValue(page()); });
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("renders native admin layout and system outcomes", async () => {
  render(<AuditLogsClient accessToken="token" />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading audit events");
  expect(await screen.findByText("Recording worker")).toBeVisible();
  expect(screen.getByText("Retry scheduled")).toBeVisible();
  expect(screen.getByText("Failed", { selector: "span" })).toHaveClass("bg-red-50");
  expect(screen.getByRole("main")).toHaveClass("max-w-5xl", "px-6", "py-7");
  expect(screen.getByRole("link", { name: "Back to Administration" })).toHaveAttribute("href", "/admin");
  expect(screen.getByRole("table")).toHaveClass("min-w-[720px]");
});

it("applies exact filters and resets to the first page", async () => {
  render(<AuditLogsClient accessToken="token" />);
  await screen.findByText("Recording worker");
  fireEvent.change(screen.getByLabelText("Actor"), { target: { value: "ADMIN@EXAMPLE.TEST" } });
  fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "failed" } });
  fireEvent.change(screen.getByLabelText("Event type"), { target: { value: "recording.processing" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("token", { actor_upn: "admin@example.test", outcome: "failed", event_type: "recording.processing" }, undefined, expect.any(AbortSignal)));
  fireEvent.click(screen.getByRole("button", { name: "Reset" }));
  await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("token", {}, undefined, expect.any(AbortSignal)));
  expect(screen.getByLabelText("Actor")).toHaveValue("");
});

it("uses next and previous cursors and refresh starts a new traversal", async () => {
  vi.mocked(getAuditEvents).mockResolvedValueOnce(page([event], "cursor-2")).mockResolvedValueOnce(page([{ ...event, id: "second" }])).mockResolvedValue(page([event], "cursor-2"));
  render(<AuditLogsClient accessToken="token" />);
  await screen.findByText("Recording worker");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("token", { from: page().window_start, to: page().window_end }, "cursor-2", expect.any(AbortSignal)));
  await screen.findByText("Page 2 · 1 events");
  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  await screen.findByText("Page 1 · 1 events");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(getAuditEvents).toHaveBeenCalledTimes(4));
  expect(getAuditEvents).toHaveBeenLastCalledWith("token", {}, undefined, expect.any(AbortSignal));
});

it("ignores stale responses and aborts replaced requests", async () => {
  let resolveOld!: (value: AuditEventsPage) => void;
  vi.mocked(getAuditEvents).mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; })).mockResolvedValue(page([]));
  render(<AuditLogsClient accessToken="token" />);
  const signal = vi.mocked(getAuditEvents).mock.calls[0][3]!;
  fireEvent.click(screen.getByRole("button", { name: "Reset" }));
  await screen.findByText("No audit events match these filters.");
  expect(signal.aborted).toBe(true);
  await act(async () => resolveOld(page()));
  expect(screen.queryByText("Recording worker")).not.toBeInTheDocument();
});

it("clears sensitive rows on permission loss", async () => {
  vi.mocked(getAuditEvents).mockResolvedValueOnce(page()).mockRejectedValue(new ApiError(403, "Forbidden"));
  render(<AuditLogsClient accessToken="token" />);
  await screen.findByText("Recording worker");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Admin access is required");
  expect(screen.queryByText("Recording worker")).not.toBeInTheDocument();
});

it("shows recoverable errors without exposing raw exceptions", async () => {
  vi.mocked(getAuditEvents).mockRejectedValueOnce(new Error("token=SECRET")).mockResolvedValue(page([]));
  render(<AuditLogsClient accessToken="token" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load audit events");
  expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
  expect(screen.queryByText("No audit events match these filters.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText("No audit events match these filters.");
});

it("validates date ranges before requesting and converts local dates to UTC", async () => {
  render(<AuditLogsClient accessToken="token" />);
  await screen.findByText("Recording worker");
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-07T10:00" } });
  fireEvent.change(screen.getByLabelText("To (exclusive)"), { target: { value: "2026-10-06T10:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(screen.getByRole("alert")).toHaveTextContent("positive date range");
  expect(getAuditEvents).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-05T10:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("token", { from: new Date("2026-10-05T10:00").toISOString(), to: new Date("2026-10-06T10:00").toISOString() }, undefined, expect.any(AbortSignal)));
});

it("shows safe details in the existing dialog and closes with Escape", async () => {
  vi.mocked(getAuditEvents).mockResolvedValue(page([{ ...event, metadata: { ...event.metadata, transcript: "SECRET", reason: "SECRET", credentials: "SECRET" } }]));
  render(<AuditLogsClient accessToken="token" />);
  const trigger = await screen.findByRole("button", { name: `View details for ${event.id}` });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("Audit Event Details");
  expect(dialog).toHaveTextContent(event.correlation_id);
  expect(dialog).not.toHaveTextContent("SECRET");
  fireEvent.keyDown(dialog, { key: "Escape", code: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await waitFor(() => expect(trigger).toHaveFocus());
});

it("supports all audit outcome badges without borrowing processing states", () => {
  render(<>{(["requested", "succeeded", "failed", "unknown"] as const).map((outcome) => <OutcomeBadge key={outcome} outcome={outcome} />)}</>);
  expect(screen.getByText("Requested")).toHaveClass("bg-blue-50");
  expect(screen.getByText("Succeeded")).toHaveClass("bg-green-50");
  expect(screen.getByText("Failed")).toHaveClass("bg-red-50");
  expect(screen.getByText("Unknown")).toHaveClass("bg-slate-100");
  expect(safeMetadata({ toString: "SECRET", transcript: "SECRET", reason: "SECRET", retry_scheduled: true })).toEqual([["retry_scheduled", true]]);
});

it("displays future event names and absent actor snapshots safely", async () => {
  vi.mocked(getAuditEvents).mockResolvedValue(page([{ ...event, event_type: "future.action", actor_type: "user", actor_upn: null, actor_id: "former-user" }]));
  render(<AuditLogsClient accessToken="token" />);
  expect(await screen.findByText("future.action")).toBeVisible();
  expect(screen.getByText("former-user")).toBeVisible();
});

it("uses predictable English date fields and rejects impossible calendar dates", async () => {
  render(<AuditLogsClient accessToken="token" />);
  await screen.findByText("Recording worker");
  const from = screen.getByLabelText("From");
  expect(from).toHaveAttribute("type", "text");
  expect(from).toHaveAttribute("placeholder", "YYYY-MM-DD HH:mm");
  expect(from).toHaveAccessibleDescription(/24|YYYY-MM-DD HH:mm/);
  fireEvent.change(from, { target: { value: "2026-02-30 10:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid date and time");
  expect(getAuditEvents).toHaveBeenCalledTimes(1);
  fireEvent.change(from, { target: { value: "2026-10-05 10:00" } });
  fireEvent.change(screen.getByLabelText("To (exclusive)"), { target: { value: "2026-10-06 10:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("token", {
    from: new Date("2026-10-05T10:00").toISOString(), to: new Date("2026-10-06T10:00").toISOString(),
  }, undefined, expect.any(AbortSignal)));
});

it.each(["2026-02-29 12:00", "2026-13-01 12:00", "2026-01-00 12:00", "2026-01-01 24:00", "2026-01-01 12:60", "06/10/2026 12:00"])("rejects invalid date %s", (value) => {
  expect(parseAuditDate(value)).toBeNull();
});

it("accepts leap days and preserves local 24-hour time", () => {
  const value = parseAuditDate("2028-02-29 14:30")!;
  expect([value.getFullYear(), value.getMonth(), value.getDate(), value.getHours(), value.getMinutes()]).toEqual([2028, 1, 29, 14, 30]);
});

it("groups email filters and applies the existing email event and actor filters", async () => {
  vi.mocked(getAuditEvents).mockResolvedValue(page([{ ...event, event_type: "email.send", outcome: "succeeded", actor_id: "email_sender" }]));
  render(<AuditLogsClient accessToken="token" />);
  expect(await screen.findByText("Email sender")).toBeVisible();
  expect(screen.getByText("Email submission", { selector: "td" })).toBeVisible();
  expect(screen.getByRole("group", { name: "Email approval & sending" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Email approval requested" })).toHaveValue("email.approval_requested");
  expect(screen.getByRole("option", { name: "Email approved" })).toHaveValue("email.approved");
  fireEvent.change(screen.getByLabelText("Event type"), { target: { value: "email.send" } });
  fireEvent.change(screen.getByLabelText("Actor"), { target: { value: "email_sender" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("token", {
    event_type: "email.send", actor_id: "email_sender",
  }, undefined, expect.any(AbortSignal)));
  expect(screen.getByText(/delivery is not confirmed/)).toBeVisible();
});

it("provides a clear empty-state action that resets applied filters", async () => {
  vi.mocked(getAuditEvents).mockResolvedValue(page([]));
  render(<AuditLogsClient accessToken="token" />);
  expect(await screen.findByText(/Try a wider date range/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  await waitFor(() => expect(getAuditEvents).toHaveBeenCalledTimes(2));
  expect(getAuditEvents).toHaveBeenLastCalledWith("token", {}, undefined, expect.any(AbortSignal));
});

it("summarizes applied filters rather than unsaved edits and clears them on reset", async () => {
  render(<AuditLogsClient accessToken="token" />);
  await screen.findByText("Recording worker");
  const summary = screen.getByLabelText("Active filters");
  expect(summary).toHaveTextContent("Event: All events");
  expect(summary).toHaveTextContent("Date range: Last 7 days");
  fireEvent.change(screen.getByLabelText("Actor"), { target: { value: "ADMIN@EXAMPLE.TEST" } });
  fireEvent.change(screen.getByLabelText("Event type"), { target: { value: "email.approved" } });
  fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "succeeded" } });
  expect(summary).toHaveTextContent("Actor: All actors");
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(summary).toHaveTextContent("Actor: admin@example.test"));
  expect(summary).toHaveTextContent("Event: Email approved");
  expect(summary).toHaveTextContent("Outcome: Succeeded");
  fireEvent.change(screen.getByLabelText("Actor"), { target: { value: "unsaved@example.test" } });
  expect(summary).not.toHaveTextContent("unsaved");
  fireEvent.click(screen.getByRole("button", { name: "Reset" }));
  await waitFor(() => expect(summary).toHaveTextContent("Actor: All actors"));
});

it("shows a page-scoped record count and a clear details button with a friendly action", async () => {
  render(<AuditLogsClient accessToken="token" />);
  expect(await screen.findByText("1 record on this page")).toBeVisible();
  const details = screen.getByRole("button", { name: `View details for ${event.id}` });
  expect(details).toHaveTextContent("View details");
  expect(details).toHaveClass("border", "rounded-md");
  fireEvent.click(details);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Action")).toBeVisible();
  expect(dialog).toHaveTextContent("Recording processing");
  expect(dialog).toHaveTextContent("recording.processing");
});
