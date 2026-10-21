import { afterEach, expect, it, vi } from "vitest";
import { getRecentMeetings } from "../api";

afterEach(() => vi.unstubAllGlobals());

it("opts into complete cached calendar history using one authenticated read only", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] });
  vi.stubGlobal("fetch", fetch);
  await getRecentMeetings("offline-token", true);
  expect(fetch).toHaveBeenCalledOnce();
  const [url, options] = fetch.mock.calls[0];
  expect(new URL(url).pathname).toBe("/calendar/recent");
  expect(new URL(url).searchParams.get("all_available")).toBe("true");
  expect(options.headers.Authorization).toBe("Bearer offline-token");
  expect(options.method ?? "GET").toBe("GET");
});
