import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { searchSavedMeetings } from "@/lib/api";
import SearchClient from "../search-client";

vi.mock("@/lib/api", () => ({ searchSavedMeetings: vi.fn() }));
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
