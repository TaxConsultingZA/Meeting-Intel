import { describe, expect, it } from "vitest";
import { formatDateTime, formatEventTime, parseInstant, resolveTimeZone } from "../time";

describe("user timezone rendering", () => {
  it.each([
    ["Asia/Shanghai", "17 Jul 2026, 15:02"],
    ["Africa/Johannesburg", "17 Jul 2026, 09:02"],
    ["UTC", "17 Jul 2026, 07:02"],
  ])("shows local date and time without technical labels for %s", (zone, expected) => {
    expect(formatDateTime("2026-07-17T07:02:00Z", zone)).toBe(expected);
  });
  it("converts UTC to South Africa, including date rollover", () => {
    const result = formatDateTime("2026-08-27T23:30:00Z", "Africa/Johannesburg");
    expect(result).toContain("28"); expect(result).toContain("01:30");
  });
  it("converts UTC to China, including date rollover", () => {
    const result = formatDateTime("2026-08-27T18:30:00Z", "Asia/Shanghai");
    expect(result).toContain("28"); expect(result).toContain("02:30");
  });
  it("does not double-convert explicit offsets or UTC", () => {
    expect(parseInstant("2026-08-28T10:00:00+02:00")?.toISOString()).toBe("2026-08-28T08:00:00.000Z");
    expect(parseInstant("2026-08-28T08:00:00Z")?.toISOString()).toBe("2026-08-28T08:00:00.000Z");
    expect(parseInstant("2026-08-28T08:00:00.0000000")?.toISOString()).toBe("2026-08-28T08:00:00.000Z");
  });
  it("prefers a reliable profile zone, otherwise browser IANA zone", () => {
    expect(resolveTimeZone("South Africa Standard Time", "Asia/Shanghai")).toBe("Africa/Johannesburg");
    expect(resolveTimeZone(null, "Asia/Shanghai")).toBe("Asia/Shanghai");
    expect(resolveTimeZone(null, "Africa/Johannesburg")).toBe("Africa/Johannesburg");
  });
  it("uses the displayed timezone for Today/Tomorrow and marks cross-day end", () => {
    const value = formatEventTime("2026-08-27T21:30:00Z", "2026-08-27T22:30:00Z", "Africa/Johannesburg", new Date("2026-08-27T12:00:00Z"));
    expect(value.dateLabel).toBe("Today"); expect(value.timeRange).toContain("23:30");
    expect(value.timeRange).toContain("28"); expect(value.timeRange).toContain("00:30");
    expect(value.duration).toBe("60 min");
  });
  it("preserves descriptive legacy dates and rejects invalid ISO", () => {
    expect(formatDateTime("Date not recorded", "Asia/Shanghai")).toBe("Date not recorded");
    expect(parseInstant("not a date")).toBeNull();
  });
});
