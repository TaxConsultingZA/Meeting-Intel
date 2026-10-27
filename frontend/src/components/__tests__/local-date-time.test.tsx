import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import LocalDateTime from "../local-date-time";
import { formatDateTime } from "@/lib/time";

afterEach(cleanup);

it("uses Africa/Johannesburg regardless of browser timezone", () => {
  const instant = "2026-07-17T07:02:00Z";
  const zone = "Africa/Johannesburg";
  render(<LocalDateTime value={instant} />);
  const date = screen.getByText(formatDateTime(instant, zone) + " SAST");
  expect(date).not.toHaveAttribute("title");
  expect(date.textContent).not.toMatch(/UTC|GMT|Africa\/|Asia\//);
});

it("formats legacy space-separated UTC timestamps instead of showing raw text",()=>{
  render(<LocalDateTime value="2026-09-01 08:41:58+00:00"/>);
  expect(screen.getByText("01 Sept 2026, 10:41 SAST")).toBeVisible();
});

it("describes a missing recording date without inventing one",()=>{
  render(<LocalDateTime value={null} unavailable="Recording date unavailable"/>);
  expect(screen.getByText("Recording date unavailable")).toBeVisible();
});

it.each([
  ["2026-09-01T08:41:58Z", "01 Sept 2026, 10:41 SAST", "01 Sept 2026, 16:41 SAST"],
  ["2026-10-22T06:50:32Z", "22 Oct 2026, 08:50 SAST", "22 Oct 2026, 14:50 SAST"],
])("renders Graph instant %s in South Africa rather than the Teams UTC+8 wall clock", (instant, southAfrica, china) => {
  expect(formatDateTime(instant, "Asia/Shanghai")).toBe(china.replace(" SAST", ""));
  render(<LocalDateTime value={instant} />);
  expect(screen.getByText(southAfrica)).toBeVisible();
  expect(screen.queryByText(china)).not.toBeInTheDocument();
});

it.each(["2026-10-22T06:50:32Z","2026-10-22T14:50:32+08:00","2026-10-22T08:50:32+02:00"])("converts %s once",value=>{
 render(<LocalDateTime value={value}/>); expect(screen.getByText("22 Oct 2026, 08:50 SAST")).toBeVisible();
});
it.each([null,"","invalid"])("leaves %s unavailable",value=>{
 render(<LocalDateTime value={value} unavailable="Time unavailable"/>); expect(screen.getByText("Time unavailable")).toBeVisible();
});
