import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError, searchSavedMeetings } from "@/lib/api";
import SearchClient from "../search-client";

vi.mock("@/lib/api", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/api")>(), searchSavedMeetings: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const rows = [{ id: "m1", title: "Budget meeting", recorded_at: null, matched_summary: true, matched_action_items: true }];
function submit(q = "budget") {
  fireEvent.change(screen.getByLabelText("Keyword"), { target: { value: q } });
  fireEvent.submit(screen.getByRole("form", { name: "Search saved meeting content" }));
}

it("only searches on nonempty submit and links matching meetings to their detail pages", async () => {
  vi.mocked(searchSavedMeetings).mockResolvedValue(rows);
  render(<SearchClient accessToken="token" />);
  submit("   ");
  expect(searchSavedMeetings).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Keyword"), { target: { value: "budget" } });
  expect(searchSavedMeetings).not.toHaveBeenCalled();
  submit(" budget ");
  expect(await screen.findByRole("link", { name: "Budget meeting" })).toHaveAttribute("href", "/meetings/m1");
  expect(screen.getByText("Matched: summary and action items")).toBeVisible();
  expect(searchSavedMeetings).toHaveBeenCalledExactlyOnceWith("token", "budget", expect.any(AbortSignal));
});

it("shows loading, empty, and safe failure states without retaining previous results", async () => {
  vi.mocked(searchSavedMeetings).mockResolvedValueOnce(rows);
  render(<SearchClient accessToken="token" />);
  submit();
  await screen.findByRole("link", { name: "Budget meeting" });
  let resolve!: (value: typeof rows) => void;
  vi.mocked(searchSavedMeetings).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  submit("absent");
  expect(screen.getByRole("status", { name: "Search loading" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Budget meeting" })).not.toBeInTheDocument();
  resolve([]);
  expect(await screen.findByText("No matching saved meetings.")).toBeVisible();
  vi.mocked(searchSavedMeetings).mockRejectedValueOnce(new Error("secret upstream transcript"));
  submit();
  expect(await screen.findByRole("alert")).toHaveTextContent("Search could not be completed. Please try again.");
  expect(screen.queryByText(/secret upstream/)).not.toBeInTheDocument();
  expect(screen.queryByText("No matching saved meetings.")).not.toBeInTheDocument();
});

it("ignores an obsolete response when another search starts", async () => {
  let resolve!: (value: typeof rows) => void;
  vi.mocked(searchSavedMeetings).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValueOnce([]);
  render(<SearchClient accessToken="token" />);
  submit("old");
  submit("new");
  await screen.findByText("No matching saved meetings.");
  resolve(rows);
  await waitFor(() => expect(screen.queryByRole("link", { name: "Budget meeting" })).not.toBeInTheDocument());
});

it("identifies a decision-only match and links it to the related meeting", async () => {
  vi.mocked(searchSavedMeetings).mockResolvedValueOnce([{ ...rows[0], matched_summary: false,
    matched_action_items: false, matched_decisions: true }]);
  render(<SearchClient accessToken="token" />);
  submit("decision");
  expect(await screen.findByText("Matched: decisions")).toBeVisible();
  expect(screen.getByRole("link", { name: "Budget meeting" })).toHaveAttribute("href", "/meetings/m1");
});

it("retries the failed submitted query while preserving a new input draft", async () => {
  vi.mocked(searchSavedMeetings).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(rows);
  render(<SearchClient accessToken="token" />);
  submit("budget");
  await screen.findByRole("alert");
  fireEvent.change(screen.getByLabelText("Keyword"), { target: { value: "new draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByRole("link", { name: "Budget meeting" });
  expect(searchSavedMeetings).toHaveBeenLastCalledWith("token", "budget", expect.any(AbortSignal));
  expect(screen.getByLabelText("Keyword")).toHaveValue("new draft");
});

it.each([401, 403])("clears results and explains permission failure %s", async status => {
  vi.mocked(searchSavedMeetings).mockResolvedValueOnce(rows).mockRejectedValueOnce(new ApiError(status, "Access denied."));
  render(<SearchClient accessToken="token" />);
  submit();
  await screen.findByRole("link", { name: "Budget meeting" });
  submit();
  expect(await screen.findByRole("alert")).toHaveTextContent("Access denied.");
  expect(screen.queryByRole("link", { name: "Budget meeting" })).not.toBeInTheDocument();
});

it("restores only the same user's draft after remount without automatically searching", async () => {
  sessionStorage.clear();
  const view = render(<SearchClient accessToken="token" userKey="local@example.test" />);
  fireEvent.change(screen.getByLabelText("Keyword"), { target: { value: "draft keyword" } });
  view.unmount();
  const other = render(<SearchClient accessToken="other" userKey="other@example.test" />);
  expect(screen.getByLabelText("Keyword")).toHaveValue("");
  other.unmount();
  render(<SearchClient accessToken="renewed-token" userKey="local@example.test" />);
  await waitFor(() => expect(screen.getByLabelText("Keyword")).toHaveValue("draft keyword"));
  expect(searchSavedMeetings).not.toHaveBeenCalled();
  sessionStorage.clear();
});
