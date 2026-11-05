import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import MeetingCardDate from "../meeting-card-date";
import type { MeetingOut } from "@/lib/types";
afterEach(cleanup);
it.each(["2026-10-30T09:30:00Z", "2026-10-30T11:30:00+02:00", "2026-10-30T09:30:00.0000000+00:00"])("renders a full South African date for %s", value => {
 render(<MeetingCardDate meeting={{ card_date: { value, source: "meeting", reason: null } } as MeetingOut} />);
 expect(screen.getByText("30 Oct 2026, 11:30 SAST")).toBeInTheDocument();
});
it("labels recording time and handles midnight rollover", () => {
 render(<MeetingCardDate meeting={{ card_date: { value: "2026-10-30T23:30:00Z", source: "recording", reason: "No verified start" } } as MeetingOut} />);
 expect(screen.getByText("Recording time: 31 Oct 2026, 01:30 SAST")).toBeInTheDocument();
});
it.each([null, "invalid", "2026-02-30T09:30:00Z", "2026-10-30T09:30:00"])("explains missing or invalid dates", value => {
 render(<MeetingCardDate meeting={{ card_date: { value, source: "unavailable", reason: "No reliable source" } } as MeetingOut} />);
 expect(screen.getByText("Date not available")).toHaveAttribute("title", "No reliable source");
});
