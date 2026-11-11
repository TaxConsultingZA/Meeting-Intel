import { describe, expect, it } from "vitest";
import { bucketLabel, makeBuckets, niceTicks, rangeLabel } from "./usage-metrics";

describe("usage metric chart helpers", () => {
  it("keeps every date exactly once while compacting a medium range", () => {
    const buckets = makeBuckets("2026-01-01", "2026-02-15");
    expect(buckets).toHaveLength(7);
    expect(buckets[0]).toMatchObject({ start: "2026-01-01", end: "2026-01-07" });
    expect(buckets.at(-1)).toMatchObject({ start: "2026-02-12", end: "2026-02-15" });
    for (let index = 1; index < buckets.length; index++) expect(buckets[index].start > buckets[index - 1].end).toBe(true);
  });

  it("uses integer, unique, evenly spaced axes including small values", () => {
    expect(niceTicks(2)).toEqual([0, 1, 2]);
    expect(niceTicks(13)).toEqual([0, 5, 10, 15]);
    expect(niceTicks(0)).toEqual([0]);
  });

  it("makes compact same-month, cross-month and cross-year labels explicit", () => {
    expect(bucketLabel("2026-10-14", "2026-10-20")).toBe("14–20 Oct");
    expect(bucketLabel("2026-10-28", "2026-11-03")).toBe("28 Oct–3 Nov");
    expect(bucketLabel("2026-12-30", "2027-01-05")).toBe("30 Dec 2026–5 Jan 2027");
  });

  it("keeps a small-value axis readable without duplicate ticks", () => {
    expect(niceTicks(1)).toEqual([0, 1, 2]);
    expect(niceTicks(10)).toEqual([0, 5, 10]);
  });

  it("compacts mobile buckets without dropping dates or totals", () => {
    const buckets = makeBuckets("2026-08-14", "2026-11-11", 9);
    expect(buckets).toHaveLength(9);
    expect(buckets[0].start).toBe("2026-08-14");
    expect(buckets.at(-1)?.end).toBe("2026-11-11");
    for (let index = 1; index < buckets.length; index++) expect(buckets[index].start > buckets[index - 1].end).toBe(true);
  });

  it("shows years in the applied range", () => {
    const groups = [{ key: "1", name: "Africorp", is_selectable: true }];
    expect(rangeLabel({ from: "2026-08-14", to: "2026-11-11", group: "1" }, groups)).toBe("14 Aug–11 Nov 2026 · Africorp");
    expect(rangeLabel({ from: "2026-12-30", to: "2027-01-05", group: "all" }, groups)).toBe("30 Dec 2026–5 Jan 2027 · All Business Units");
  });
});
