import { describe, it, expect } from "vitest";

// Pure helpers extracted from dashboard-client.tsx — tested in isolation.

function formatUpn(upn: string | null | undefined): string {
  if (!upn) return "";
  return upn
    .split("@")[0]
    .split(".")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

function formatEventTime(start: string | null, end: string | null) {
  if (!start) return { dateLabel: "—", timeRange: "—", duration: "" };
  const s = new Date(start);
  const e = end ? new Date(end) : null;
  const now = new Date();
  const isToday = s.toDateString() === now.toDateString();
  const isTomorrow =
    s.toDateString() === new Date(now.getTime() + 86400000).toDateString();
  const dateLabel = isToday
    ? "Today"
    : isTomorrow
    ? "Tomorrow"
    : s.toLocaleDateString("en-ZA", { weekday: "short", day: "2-digit", month: "short" });
  const fmt = (d: Date) =>
    d.toLocaleTimeString("en-ZA", { hour: "2-digit", minute: "2-digit" });
  const timeRange = `${fmt(s)}${e ? ` – ${fmt(e)}` : ""}`;
  const duration = e
    ? `${Math.round((e.getTime() - s.getTime()) / 60000)} min`
    : "";
  return { dateLabel, timeRange, duration };
}

describe("formatUpn", () => {
  it("converts standard UPN to display name", () => {
    expect(formatUpn("jane.doe@taxconsulting.co.za")).toBe("Jane Doe");
  });

  it("capitalises first letter of each part", () => {
    expect(formatUpn("john.smith@domain.com")).toBe("John Smith");
  });

  it("handles single-part username", () => {
    expect(formatUpn("alice@domain.com")).toBe("Alice");
  });

  it("returns empty string for null", () => {
    expect(formatUpn(null)).toBe("");
  });

  it("returns empty string for undefined", () => {
    expect(formatUpn(undefined)).toBe("");
  });

  it("returns empty string for empty string", () => {
    expect(formatUpn("")).toBe("");
  });
});

describe("formatEventTime", () => {
  it("returns dashes for null start", () => {
    const result = formatEventTime(null, null);
    expect(result.dateLabel).toBe("—");
    expect(result.timeRange).toBe("—");
    expect(result.duration).toBe("");
  });

  it("labels today's event as Today", () => {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 10, 0).toISOString();
    const { dateLabel } = formatEventTime(start, null);
    expect(dateLabel).toBe("Today");
  });

  it("labels tomorrow's event as Tomorrow", () => {
    const tomorrow = new Date(Date.now() + 86400000);
    const start = new Date(
      tomorrow.getFullYear(), tomorrow.getMonth(), tomorrow.getDate(), 14, 0
    ).toISOString();
    const { dateLabel } = formatEventTime(start, null);
    expect(dateLabel).toBe("Tomorrow");
  });

  it("calculates duration correctly", () => {
    const start = new Date("2026-07-01T09:00:00Z").toISOString();
    const end = new Date("2026-07-01T10:30:00Z").toISOString();
    const { duration } = formatEventTime(start, end);
    expect(duration).toBe("90 min");
  });

  it("omits duration when no end time", () => {
    const start = new Date("2026-07-01T09:00:00Z").toISOString();
    const { duration } = formatEventTime(start, null);
    expect(duration).toBe("");
  });

  it("includes time range with separator", () => {
    const start = new Date("2026-07-01T09:00:00Z").toISOString();
    const end = new Date("2026-07-01T10:00:00Z").toISOString();
    const { timeRange } = formatEventTime(start, end);
    expect(timeRange).toContain("–");
  });
});
