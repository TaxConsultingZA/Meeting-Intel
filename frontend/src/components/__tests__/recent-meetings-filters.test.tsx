import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import RecentMeetings from "../recent-meetings";
import * as api from "@/lib/api";
import type { RecentMeeting } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  getRecentMeetings: vi.fn(), getProcessingRequests: vi.fn(), requestRecordingProcessing: vi.fn(),
  decideRecordingProcessing: vi.fn(), processRecentMeeting: vi.fn(),
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); sessionStorage.clear(); });

it("reveals loaded external meetings hidden only by time and recording filters without refetching", async () => {
  const event = (subject: string, days: number, action: RecentMeeting["action"]): RecentMeeting => ({
    event_id: subject, subject, action, status: "ended",
    start: new Date(Date.now() - days * 86400000).toISOString(),
    end: new Date(Date.now() - days * 86400000 + 3600000).toISOString(),
    start_tz: "UTC", organizer_name: "External organiser", organizer_email: "host@external.example",
    attendees: [], attendee_count: 0, platform: "Teams", location: null,
  });
  vi.mocked(api.getRecentMeetings).mockResolvedValue([
    event("Older recording", 10, "process"), event("Recent without recording", 1, "no_recording"),
  ]);
  vi.mocked(api.getProcessingRequests).mockResolvedValue([]);
  render(<RecentMeetings token="offline-token" cacheIdentity="attendee@example.test" isSubscribed />);
  expect(await screen.findByText("No meetings match these filters.")).toBeInTheDocument();
  expect(screen.queryByText("Older recording")).not.toBeInTheDocument();
  expect(screen.queryByText("Recent without recording")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Time" }), { target: { value: "all" } });
  expect(screen.getByText("Older recording")).toBeInTheDocument();
  expect(screen.queryByText("Recent without recording")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Recording" }), { target: { value: "all" } });
  expect(screen.getByText("Recent without recording")).toBeInTheDocument();
  expect(api.getRecentMeetings).toHaveBeenCalledOnce();
  expect(api.processRecentMeeting).not.toHaveBeenCalled();
  expect(api.requestRecordingProcessing).not.toHaveBeenCalled();
});
