import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import LocalDateTime from "../local-date-time";
import { formatDateTime, resolveTimeZone } from "@/lib/time";

afterEach(cleanup);

it("uses browser local time without a timezone tooltip", () => {
  const instant = "2026-07-17T07:02:00Z";
  const zone = resolveTimeZone(null, Intl.DateTimeFormat().resolvedOptions().timeZone);
  render(<LocalDateTime value={instant} />);
  const date = screen.getByText(formatDateTime(instant, zone));
  expect(date).not.toHaveAttribute("title");
  expect(date.textContent).not.toMatch(/UTC|GMT|Africa\/|Asia\//);
});
