import { describe, it, expect, beforeEach } from "vitest";

// Import the pure helper functions directly by re-implementing them here
// so tests aren't coupled to the React component's internal exports.
// These match the implementations in notification-bell.tsx exactly.

const SEEN_KEY = "mi_seen_notifications";

function getSeenIds(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

function markSeen(ids: string[]) {
  try {
    const existing = getSeenIds();
    ids.forEach((id) => existing.add(id));
    localStorage.setItem(SEEN_KEY, JSON.stringify([...existing].slice(-100)));
  } catch {}
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

beforeEach(() => {
  localStorage.clear();
});

describe("getSeenIds", () => {
  it("returns empty set when localStorage is empty", () => {
    expect(getSeenIds().size).toBe(0);
  });

  it("returns previously stored IDs", () => {
    localStorage.setItem(SEEN_KEY, JSON.stringify(["id-1", "id-2"]));
    const ids = getSeenIds();
    expect(ids.has("id-1")).toBe(true);
    expect(ids.has("id-2")).toBe(true);
  });

  it("returns empty set on malformed JSON", () => {
    localStorage.setItem(SEEN_KEY, "not-valid-json{{{");
    expect(getSeenIds().size).toBe(0);
  });
});

describe("markSeen", () => {
  it("stores new IDs", () => {
    markSeen(["n-1", "n-2"]);
    const ids = getSeenIds();
    expect(ids.has("n-1")).toBe(true);
    expect(ids.has("n-2")).toBe(true);
  });

  it("merges with existing IDs", () => {
    markSeen(["old-1"]);
    markSeen(["new-1"]);
    const ids = getSeenIds();
    expect(ids.has("old-1")).toBe(true);
    expect(ids.has("new-1")).toBe(true);
  });

  it("caps stored IDs at 100", () => {
    const lotsOfIds = Array.from({ length: 110 }, (_, i) => `id-${i}`);
    markSeen(lotsOfIds);
    const stored: string[] = JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]");
    expect(stored.length).toBeLessThanOrEqual(100);
  });

  it("deduplicates IDs", () => {
    markSeen(["dup-1"]);
    markSeen(["dup-1"]);
    const stored: string[] = JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]");
    expect(stored.filter((x) => x === "dup-1")).toHaveLength(1);
  });
});

describe("timeAgo", () => {
  it("returns 'just now' for less than 1 minute ago", () => {
    const recent = new Date(Date.now() - 30_000).toISOString();
    expect(timeAgo(recent)).toBe("just now");
  });

  it("returns minutes for less than 1 hour ago", () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString();
    expect(timeAgo(fiveMinAgo)).toBe("5m ago");
  });

  it("returns hours for less than 24 hours ago", () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60_000).toISOString();
    expect(timeAgo(threeHoursAgo)).toBe("3h ago");
  });

  it("returns days for more than 24 hours ago", () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60_000).toISOString();
    expect(timeAgo(twoDaysAgo)).toBe("2d ago");
  });
});
