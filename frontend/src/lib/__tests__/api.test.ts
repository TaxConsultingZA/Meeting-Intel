import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// Reset between tests
beforeEach(() => {
  mockFetch.mockReset();
  window.localStorage.removeItem("meeting-intel.pending-calendar-sync");
});

function makeResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

describe("syncCalendarsNow", () => {
  it("observes a durable run until completion without another POST", async () => {
    vi.useFakeTimers();
    try {
      const run = { id: "run-1", status: "running", succeeded: 0, failed: 0, skipped: 0,
        created: 0, updated: 0, error_category: null, retry_allowed: false };
      mockFetch.mockResolvedValueOnce(makeResponse(run, 202))
        .mockResolvedValueOnce(makeResponse(run))
        .mockResolvedValueOnce(makeResponse({ ...run, status: "success", succeeded: 1, created: 3, retry_allowed: true }));
      const { syncCalendarsNow } = await import("../api");
      const pending = syncCalendarsNow("offline-token");
      await vi.advanceTimersByTimeAsync(4_000);
      await expect(pending).resolves.toMatchObject({ status: "success", succeeded: 1, created: 3 });
      expect(mockFetch.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(1);
      expect(mockFetch.mock.calls.slice(1).every(([url]) => url.endsWith("/calendar/sync?run_id=run-1"))).toBe(true);
    } finally { vi.useRealTimers(); }
  });

  it("recovers a lost acceptance response by its original id without another POST", async () => {
    const run = { status: "success", succeeded: 1, failed: 0, skipped: 0, created: 2, updated: 0,
      error_category: null, retry_allowed: true };
    mockFetch.mockRejectedValueOnce(new TypeError("Network lost"));
    mockFetch.mockImplementationOnce((url: string) => Promise.resolve(makeResponse({ ...run, id: new URL(url).searchParams.get("run_id") })));
    const { syncCalendarsNow } = await import("../api");
    await expect(syncCalendarsNow("offline-token")).resolves.toMatchObject({ status: "success", created: 2 });
    const id = JSON.parse(mockFetch.mock.calls[0][1].body).request_id;
    expect(new URL(mockFetch.mock.calls[1][0]).searchParams.get("run_id")).toBe(id);
    expect(mockFetch.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(1);
  });

  it("keeps an unknown outcome blocked without replaying the operation", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ id: "run-1", status: "unknown", created: 2,
      updated: 0, succeeded: 1, failed: 0, skipped: 0, retry_allowed: false, error_category: "interrupted" }, 202));
    const { syncCalendarsNow } = await import("../api");
    await expect(syncCalendarsNow("offline-token")).rejects.toMatchObject({ syncUnconfirmed: true });
    expect(mockFetch).toHaveBeenCalledOnce();
  });

  it("preserves the 30-second deadline for ordinary reads", async () => {
    vi.useFakeTimers();
    try {
      mockFetch.mockImplementationOnce((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      }));
      const { getAllMeetings } = await import("../api");
      const pending = expect(getAllMeetings("offline-token")).rejects.toMatchObject({ status: 408 });
      await vi.advanceTimersByTimeAsync(30_000);
      await pending;
      expect(mockFetch.mock.calls[0][1].signal.aborted).toBe(true);
      expect(mockFetch).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("makes exactly one authenticated POST without target users or recording options", async () => {
    const result = { id: "completed-run", status: "success", succeeded: 3, failed: 0, skipped: 0,
      created: 2, updated: 4, error_category: null, retry_allowed: true };
    mockFetch.mockResolvedValueOnce(makeResponse(result));
    const { syncCalendarsNow } = await import("../api");
    expect(await syncCalendarsNow("offline-token")).toEqual(result);
    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, init] = mockFetch.mock.calls[0];
    expect(new URL(url).pathname).toBe("/calendar/sync");
    expect(JSON.parse(init.body).request_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(init).toMatchObject({ method: "POST", headers: { Authorization: "Bearer offline-token" } });
  });
  it("does not retry a failed sync POST", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ error: "Unavailable" }, 503))
      .mockResolvedValueOnce(makeResponse({ error: "Not confirmed" }, 404));
    const { syncCalendarsNow } = await import("../api");
    await expect(syncCalendarsNow("offline-token")).rejects.toThrow();
    expect(mockFetch.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(1);
  });

  it("retains an unconfirmed request across reload and only reads its original id", async () => {
    window.localStorage.setItem("meeting-intel.pending-calendar-sync", "pending-before-reload");
    mockFetch.mockResolvedValueOnce(makeResponse({ error: "Not confirmed" }, 404));
    const { syncCalendarsNow } = await import("../api");
    await expect(syncCalendarsNow("offline-token")).rejects.toMatchObject({ syncUnconfirmed: true });
    expect(new URL(mockFetch.mock.calls[0][0]).searchParams.get("run_id")).toBe("pending-before-reload");
    expect(mockFetch.mock.calls.some(([, init]) => init.method === "POST")).toBe(false);
    expect(window.localStorage.getItem("meeting-intel.pending-calendar-sync")).toBe("pending-before-reload");
  });
});

describe("getAuditEvents", () => {
  it("uses the existing API with safe query encoding, bearer auth, and no caching", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ items: [], next_cursor: null }));
    const { getAuditEvents } = await import("../api");
    await getAuditEvents("token", { actor_upn: "admin+audit@example.test", outcome: "failed" }, "cursor");
    const [url, init] = mockFetch.mock.calls[0];
    const query = new URL(url).searchParams;
    expect(query.get("actor_upn")).toBe("admin+audit@example.test");
    expect(query.get("cursor")).toBe("cursor");
    expect(query.get("limit")).toBe("50");
    expect(init.cache).toBe("no-store");
    expect(init.headers.Authorization).toBe("Bearer token");
  });
  it("forwards cancellation to the fetch wrapper", async () => {
    const outer = new AbortController();
    mockFetch.mockImplementationOnce((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    const { getAuditEvents } = await import("../api");
    const pending = getAuditEvents("token", {}, undefined, outer.signal);
    outer.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("getApprovedActionItems", () => {
  it("uses only GET with bearer auth, uncached results and literal query encoding", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ items: [], has_more: false, viewer_upn: "alice@example.test" }));
    const { getApprovedActionItems } = await import("../api");
    await getApprovedActionItems("token", { view: "all", meeting: "Budget & Tax", owner: "Alice+team", deadline: "Monday", offset: 50 });
    const [url, init] = mockFetch.mock.calls[0];
    const query = new URL(url).searchParams;
    expect(new URL(url).pathname).toBe("/action-items");
    expect(query.get("meeting")).toBe("Budget & Tax");
    expect(query.get("owner")).toBe("Alice+team");
    expect(query.get("deadline")).toBe("Monday");
    expect(query.get("offset")).toBe("50");
    expect(init.method).toBeUndefined();
    expect(init.body).toBeUndefined();
    expect(init.cache).toBe("no-store");
    expect(init.headers.Authorization).toBe("Bearer token");
  });
});

describe("getAllMeetings", () => {
  it("passes the bearer token", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse([]));
    const { getAllMeetings } = await import("../api");
    await getAllMeetings("alice@taxconsulting.co.za");
    const [, init] = mockFetch.mock.calls[0];
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer alice@taxconsulting.co.za",
    });
  });

  it("returns parsed JSON on success", async () => {
    const data = [{ id: "m1", title: "Budget", state: "sent" }];
    mockFetch.mockResolvedValueOnce(makeResponse(data));
    const { getAllMeetings } = await import("../api");
    const result = await getAllMeetings("alice@taxconsulting.co.za");
    expect(result).toEqual(data);
  });

  it("throws on non-2xx response", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ detail: "Not found" }, 404));
    const { getAllMeetings } = await import("../api");
    await expect(getAllMeetings("alice@taxconsulting.co.za")).rejects.toThrow("404");
  });
});

describe("approveMeeting", () => {
  it("sends POST method", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ ok: true, state: "sent" }));
    const { approveMeeting } = await import("../api");
    await approveMeeting("meeting-id", "alice@taxconsulting.co.za", [], "reviewed-fingerprint");
    const [, init] = mockFetch.mock.calls[0];
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ recipients: [], expected_fingerprint: "reviewed-fingerprint" });
  });
});

describe("getMe account-state errors", () => {
  it("returns null only for the explicit application unregistered response", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ detail: "Not registered on the platform" }, 404));
    const { getMe } = await import("../api");
    await expect(getMe("token")).resolves.toBeNull();
  });

  it("rejects a platform or unexpected 404", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse("Application not found", 404));
    const { getMe } = await import("../api");
    await expect(getMe("token")).rejects.toThrow("404");
  });

  it.each([
    ["backend 5xx", () => Promise.resolve(makeResponse({ detail: "Internal Server Error" }, 503))],
    ["network failure", () => Promise.reject(new TypeError("Failed to fetch"))],
  ])("rejects %s instead of returning an unregistered result", async (_label, response) => {
    mockFetch.mockImplementationOnce(response);
    const { getMe } = await import("../api");
    await expect(getMe("token")).rejects.toThrow();
  });
});

describe("sendMeetingCopyToSelf", () => {
  it("posts only the caller's fixed self-copy recipient", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ ok: true, sent: true }));
    const { sendMeetingCopyToSelf } = await import("../api");
    await sendMeetingCopyToSelf("meeting-id", "alice@taxconsulting.co.za", "token-1");
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toContain("/reviews/meeting-id/send-copy");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      recipient_upn: "alice@taxconsulting.co.za",
    });
  });
});

describe("previewMeetingEmail", () => {
  it("requests the exact email preview without sending", async () => {
    mockFetch.mockResolvedValueOnce(
      makeResponse({ subject: "Meeting Notes", html: "<p>Preview</p>", recipients: ["alice@example.com"], fingerprint: "reviewed-fingerprint" }),
    );
    const { previewMeetingEmail } = await import("../api");
    const result = await previewMeetingEmail("meeting-id", "token-1", ["alice@example.com"]);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toContain("/reviews/meeting-id/email-preview");
    expect((init as RequestInit).method).toBeUndefined();
    expect(result.subject).toBe("Meeting Notes");
    expect(url).toContain("recipients=alice%40example.com");
    expect(result.fingerprint).toBe("reviewed-fingerprint");
  });
});

describe("importRecording", () => {
  it("sends drive item id and drive id in body", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse({ ok: true }));
    const { importRecording } = await import("../api");
    await importRecording("item-1", "drive-1", "alice@taxconsulting.co.za");
    const [, init] = mockFetch.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.drive_item_id).toBe("item-1");
    expect(body.drive_id).toBe("drive-1");
  });
});

describe("getNotifications", () => {
  it("calls /notifications endpoint", async () => {
    mockFetch.mockResolvedValueOnce(makeResponse([]));
    const { getNotifications } = await import("../api");
    await getNotifications("alice@taxconsulting.co.za");
    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("/notifications");
  });
});
