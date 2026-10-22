import { afterEach, expect, it, vi } from "vitest";
import { getApprovedActionItems, getRecordingJobs, searchSavedMeetings } from "../api";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it("keeps the three feature reads authenticated and independently encoded through the shared client", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] });
  vi.stubGlobal("fetch", fetch);
  await Promise.all([
    getApprovedActionItems("offline-token", { view: "all", meeting: "A&B", owner: "", deadline: "", offset: 50 }),
    getRecordingJobs("offline-token", undefined, 200),
    searchSavedMeetings("offline-token", "Tax & 100% +预算"),
  ]);
  expect(fetch).toHaveBeenCalledTimes(3);
  const byPath = new Map(fetch.mock.calls.map(([url, init]) => [new URL(url).pathname, { url: new URL(url), init }]));
  expect(byPath.get("/action-items")?.url.searchParams.get("meeting")).toBe("A&B");
  expect(byPath.get("/action-items")?.url.searchParams.get("offset")).toBe("50");
  expect(byPath.get("/recordings/jobs")?.url.searchParams.get("limit")).toBe("200");
  expect(byPath.get("/reviews/search")?.url.searchParams.get("q")).toBe("Tax & 100% +预算");
  expect(byPath.get("/reviews/search")?.init.cache).toBe("no-store");
  expect(byPath.get("/action-items")?.init.cache).toBe("no-store");
  for (const { init } of byPath.values()) {
    expect(init.headers.Authorization).toBe("Bearer offline-token");
    expect(init.method ?? "GET").toBe("GET");
    expect(init.body).toBeUndefined();
  }
});

it("isolates cancellation between simultaneous action-item and search requests", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((_url: string, init: RequestInit) => new Promise((_, reject) => {
    init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  })));
  const actions = new AbortController();
  const search = new AbortController();
  const actionResult = expect(getApprovedActionItems("token", { view: "all", meeting: "", owner: "", deadline: "", offset: 0 }, actions.signal)).rejects.toMatchObject({ name: "AbortError" });
  const searchResult = expect(searchSavedMeetings("token", "budget", search.signal)).rejects.toMatchObject({ name: "AbortError" });
  actions.abort();
  await actionResult;
  expect(search.signal.aborted).toBe(false);
  search.abort();
  await searchResult;
});

it("retains the shared 30-second timeout for all three feature reads", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn().mockImplementation((_url: string, init: RequestInit) => new Promise((_, reject) => {
    init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  })));
  const pending = [
    getApprovedActionItems("token", { view: "all", meeting: "", owner: "", deadline: "", offset: 0 }),
    getRecordingJobs("token", undefined, 200), searchSavedMeetings("token", "budget"),
  ].map(promise => expect(promise).rejects.toMatchObject({ status: 408 }));
  await vi.advanceTimersByTimeAsync(30_000);
  await Promise.all(pending);
});
