import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import LocalDateTime from "../local-date-time";
import { formatDateTime, resolveTimeZone } from "@/lib/time";

afterEach(cleanup);

it("uses Africa/Johannesburg regardless of browser timezone", () => {
  const instant = "2026-07-17T07:02:00Z";
  const zone = "Africa/Johannesburg";
  render(<LocalDateTime value={instant} />);
  const date = screen.getByText(formatDateTime(instant, zone));
  expect(date).not.toHaveAttribute("title");
  expect(date.textContent).not.toMatch(/UTC|GMT|Africa\/|Asia\//);
});

it("formats legacy space-separated UTC timestamps instead of showing raw text",()=>{
  render(<LocalDateTime value="2026-09-01 08:41:58+00:00"/>);
  expect(screen.getByText("01 Sept 2026, 10:41")).toBeVisible();
});

it("describes a missing recording date without inventing one",()=>{
  render(<LocalDateTime value={null} unavailable="Recording date unavailable"/>);
  expect(screen.getByText("Recording date unavailable")).toBeVisible();
});
