import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { getAdminMeetings, getAuditEvents } from "@/lib/api";
import AdminWorkbench from "../admin-workbench";
import type { AdminMeetingOut, AuditEvent, AuditFilters } from "@/lib/types";
const fixtures = vi.hoisted(() => ({
  meetings: Array.from({ length: 9 }, (_, i): AdminMeetingOut => ({
    id: `synthetic-${i + 1}`, title: `Synthetic review ${i + 1}`, recorded_at: "2026-11-05T08:00:00Z",
    organizer_upn: "owner@example.test", owner_upn: "owner@example.test", meeting_status: "awaiting_review",
    recording_status: "tracked", job_status: null, request_status: null, access: [],
  })),
  events: Array.from({ length: 75 }, (_, i): AuditEvent => ({
    id: `synthetic-event-${i}`, occurred_at: "2026-11-05T09:00:00Z",
    event_type: "recording.completed", outcome: "succeeded", actor_type: "system", actor_id: "recording_worker",
    actor_upn: null, resource_type: "recording", resource_id: `recording-${i}`, meeting_id: "synthetic-9",
    job_id: null, correlation_id: `correlation-${i}`, metadata: {},
  })),
}));
vi.mock("@/lib/api", () => ({
  getAdminMeetings: vi.fn(async () => fixtures.meetings),
  getRecordingJobs: vi.fn(async () => []),
  getMeeting: vi.fn(async (id: string) => ({
    id, state: "awaiting_review", action_items: [], calendar_participants: [],
  })),
  getAuditEvents: vi.fn(async (_: string, filters: AuditFilters, cursor?: string) => {
    if (filters.actor_id === "simulate-error") throw new Error("Synthetic activity failure");
    const offset = Number(cursor || 0);
    return {
      items: fixtures.events.slice(offset, offset + 50), next_cursor: offset === 0 ? "50" : null,
      has_more: offset === 0, window_start: "2026-11-01T00:00:00Z", window_end: "2026-11-06T00:00:00Z",
    };
  }),
}));
vi.mock("../../meetings/[id]/meeting-detail-client", () => ({default: () => <p>Existing permission-aware meeting editor</p>}));
vi.mock("../audit-logs/audit-event-dialog", () => ({default: () => <p>Read-only event details</p>}));
afterEach(cleanup);
it("searches beyond six rows, opens Details, and continues audit pages", async () => {
 render(<AdminWorkbench accessToken="offline" callerUpn="admin@example.test" />);
 await screen.findByText("Synthetic review 9");
 expect(screen.getByLabelText("Meeting results")).toHaveAttribute("tabindex", "0");
 fireEvent.change(screen.getByLabelText("Record, ID or owner"), {target:{value:"synthetic-9"}});
 expect(screen.getAllByRole("button", {name:"Details"})).toHaveLength(1);
 fireEvent.click(screen.getByRole("button", {name:"Details"}));
 await screen.findByText("Existing permission-aware meeting editor");
 fireEvent.click(screen.getByRole("button", {name:"Load more activity for Details"}));
 await waitFor(() => expect(screen.getByText(/75 total activity records loaded/)).toBeVisible());
 expect(screen.queryByRole("button", {name:"Load more activity for Details"})).toBeNull();
});
it("reports failure, retries, and resets to the default range", async () => {
 render(<AdminWorkbench accessToken="offline" callerUpn="admin@example.test" />);
 await screen.findByText("Synthetic review 9");
 fireEvent.change(screen.getByLabelText("Actor email or system ID"), {target:{value:"simulate-error"}});
 fireEvent.click(screen.getByRole("button", {name:"Search"}));
 await screen.findByRole("alert");
 fireEvent.click(screen.getByRole("button", {name:"Retry activity"}));
 await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Activity could not be loaded"));
 fireEvent.click(screen.getByRole("button", {name:"Reset"}));
 await screen.findByText("Synthetic review 9");
 expect(screen.getByLabelText("Actor email or system ID")).toHaveValue("");
});
it("keeps all section headings visible when activity fails, then distinguishes an empty window", async () => {
 render(<AdminWorkbench accessToken="offline" callerUpn="admin@example.test" />);
 await screen.findByText("Synthetic review 9");
 vi.mocked(getAuditEvents).mockRejectedValueOnce(new Error("Synthetic activity failure"));
 fireEvent.change(screen.getByLabelText("Record, ID or owner"), {target:{value:"synthetic-9"}});
 fireEvent.click(screen.getByRole("button", {name:"Details"}));
 await screen.findByText(/Activity could not be loaded/);
 for (const name of ["Meeting & recording", "Processing & AI", "Review & actions", "Access", "Activity & email"]) {
   expect(screen.getByRole("heading", {name})).toBeVisible();
 }
 vi.mocked(getAuditEvents).mockResolvedValueOnce({items:[],next_cursor:null,has_more:false,window_start:"2026-11-01T00:00:00Z",window_end:"2026-11-06T00:00:00Z"});
 fireEvent.click(screen.getByRole("button", {name:"Retry Details activity"}));
 await screen.findByText("No verified linked activity found in the loaded query window.");
});

it("uses Johannesburg cutoffs across months and clears either date and both defaults", async () => {
 const records = [
   ["Before start", "2026-10-30T21:59:59.999Z"],
   ["At start", "2026-10-30T22:00:00.000Z"],
   ["At end", "2026-11-02T21:59:59.999Z"],
   ["After end", "2026-11-02T22:00:00.000Z"],
 ].map(([title, recorded_at], index) => ({ ...fixtures.meetings[0], id: `boundary-${index}`, title, recorded_at }));
 vi.mocked(getAdminMeetings).mockResolvedValueOnce(records).mockResolvedValueOnce(records);
 render(<AdminWorkbench accessToken="offline" callerUpn="admin@example.test" />);
 await screen.findByText("At start");
 const from = screen.getByLabelText("From (Johannesburg)");
 const to = screen.getByLabelText("To (Johannesburg)");
 expect(screen.getByRole("button", { name: "Open calendar for From (Johannesburg)" })).toBeEnabled();
 expect(screen.getByRole("button", { name: "Open calendar for To (Johannesburg)" })).toBeEnabled();
 fireEvent.change(from, { target: { value: "2026-10-31" } });
 fireEvent.change(to, { target: { value: "2026-11-02" } });
 fireEvent.click(screen.getByRole("button", { name: "Search" }));
 await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("offline", {
   from: "2026-10-30T22:00:00.000Z", to: "2026-11-02T22:00:00.000Z",
 }, undefined));
 const results = within(screen.getByLabelText("Meeting results"));
 expect(results.getByText("At start")).toBeVisible();
 expect(results.getByText("At end")).toBeVisible();
 expect(results.queryByText("Before start")).toBeNull();
 expect(results.queryByText("After end")).toBeNull();
 await waitFor(() => expect(screen.getByRole("button", { name: "Search" })).toBeEnabled());
 fireEvent.click(screen.getAllByRole("button", { name: "Clear date" })[0]);
 expect(from).toHaveValue("");
 expect(to).toHaveValue("2026-11-02");
 fireEvent.click(screen.getByRole("button", { name: "Reset" }));
 await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("offline", {}, undefined));
 expect(to).toHaveValue("");
});

it("shows English date errors and skips the audit request for invalid or reversed dates", async () => {
 render(<AdminWorkbench accessToken="offline" callerUpn="admin@example.test" />);
 await screen.findByText("Synthetic review 9");
 const calls = vi.mocked(getAuditEvents).mock.calls.length;
 const from = screen.getByLabelText("From (Johannesburg)");
 const to = screen.getByLabelText("To (Johannesburg)");
 const search = screen.getByRole("button", { name: "Search" });
 fireEvent.change(from, { target: { value: "2026-02-29" } });
 fireEvent.click(search);
 expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid date or choose one from the calendar.");
 fireEvent.change(from, { target: { value: "2026-11-03" } });
 fireEvent.change(to, { target: { value: "2026-11-02" } });
 fireEvent.click(search);
 expect(screen.getByRole("alert")).toHaveTextContent("To must be on or after From.");
 expect(getAuditEvents).toHaveBeenCalledTimes(calls);
 fireEvent.click(screen.getByRole("button", { name: "Refresh default view" }));
 expect(from).toHaveValue("");
 expect(to).toHaveValue("");
 expect(screen.queryByRole("alert")).toBeNull();
});

it("applies only explicit calendar dates across all pages and clears them on refresh", async () => {
 const records = Array.from({length: 200}, (_, index) => ({...fixtures.meetings[0], id: `page-one-${index}`, title: `First page row ${index}`}));
 const later = {...fixtures.meetings[0], id: "later", title: "Later page", recorded_at: null,
   card_date: {value: "2028-02-29T21:59:59.999Z", source: "meeting" as const, reason: null}};
 vi.mocked(getAdminMeetings).mockImplementation(async (_, offset) => offset === 0 ? records : [later]);
 render(<AdminWorkbench accessToken="offline" callerUpn="admin@example.test" />);
 await screen.findByText("Later page");
 const form = within(screen.getByText("Find a record").closest("section")!);
 expect(form.queryByRole("button", {name: /This month|Choose month/})).toBeNull();
 expect(form.queryByRole("combobox", {name: "Month"})).toBeNull();
 expect(form.queryByLabelText("Year")).toBeNull();
 fireEvent.change(screen.getByLabelText("From (Johannesburg)"), {target: {value: "2028-02-01"}});
 fireEvent.change(screen.getByLabelText("To (Johannesburg)"), {target: {value: "2028-02-29"}});
 expect(screen.getByLabelText("From (Johannesburg)")).toHaveValue("2028-02-01");
 expect(screen.getByLabelText("To (Johannesburg)")).toHaveValue("2028-02-29");
 expect(screen.getByText(/Applied dates: No date limits/)).toBeVisible();
 expect(screen.getByText("First page row 0")).toBeVisible();
 fireEvent.click(form.getByRole("button", {name: "Search"}));
 await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("offline", {
   from: "2028-01-31T22:00:00.000Z", to: "2028-02-29T22:00:00.000Z",
 }, undefined));
 expect(screen.getByText("Later page")).toBeVisible();
 expect(screen.queryByText("First page row 0")).toBeNull();
 expect(getAdminMeetings).toHaveBeenCalledWith("offline", 200);
 fireEvent.click(form.getByRole("button", {name: "Refresh default view"}));
 await waitFor(() => expect(getAuditEvents).toHaveBeenLastCalledWith("offline", {}, undefined));
 expect(screen.getByLabelText("From (Johannesburg)")).toHaveValue("");
 expect(screen.getByLabelText("To (Johannesburg)")).toHaveValue("");
 expect(screen.getByText(/Applied dates: No date limits/)).toBeVisible();
 expect(await screen.findByText("First page row 0")).toBeVisible();
 vi.mocked(getAdminMeetings).mockResolvedValue(fixtures.meetings);
});


it("focuses each section in the same dialog and restores focus on close", async () => {
  render(<AdminWorkbench accessToken="offline" callerUpn="admin@example.test" />);
  await screen.findByText("Synthetic review 9");
  fireEvent.change(screen.getByLabelText("Record, ID or owner"), { target: { value: "synthetic-9" } });
  const opener = screen.getByRole("button", { name: "Details" });
  fireEvent.click(opener);
  const dialog = await screen.findByRole("dialog", { name: "Synthetic review 9" });
  await screen.findByText("Existing permission-aware meeting editor");
  const details = within(dialog);
  for (const name of ["Meeting & recording", "Processing & AI", "Review & actions", "Access", "Activity & email"]) {
    fireEvent.click(details.getByRole("button", { name }));
    expect(details.getByRole("heading", { name })).toHaveFocus();
    expect(details.getByRole("heading", { name: "Synthetic review 9" })).toBeVisible();
    expect(details.getByRole("button", { name: "Close details" })).toBeVisible();
  }
  fireEvent.click(details.getByRole("button", { name: "Close details" }));
  await waitFor(() => expect(opener).toHaveFocus());
});


it("stops with an English error when an older API repeats the first page", async () => {
  const rows = Array.from({ length: 200 }, (_, index) => ({
    ...fixtures.meetings[0], id: `repeated-${index}`,
  }));
  const read = vi.mocked(getAdminMeetings);
  read.mockClear();
  read.mockResolvedValue(rows);
  try {
    render(<AdminWorkbench accessToken="offline" callerUpn="admin@example.test" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Records could not be loaded. Please retry.");
    expect(read.mock.calls).toEqual([["offline", 0], ["offline", 200]]);
  } finally {
    read.mockResolvedValue(fixtures.meetings);
  }
});
