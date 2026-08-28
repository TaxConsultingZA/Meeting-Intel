import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// Reset between tests
beforeEach(() => {
  mockFetch.mockReset();
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
    await approveMeeting("meeting-id", "alice@taxconsulting.co.za", []);
    const [, init] = mockFetch.mock.calls[0];
    expect((init as RequestInit).method).toBe("POST");
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
      makeResponse({ subject: "Meeting Notes", html: "<p>Preview</p>" }),
    );
    const { previewMeetingEmail } = await import("../api");
    const result = await previewMeetingEmail("meeting-id", "token-1");
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toContain("/reviews/meeting-id/email-preview");
    expect((init as RequestInit).method).toBeUndefined();
    expect(result.subject).toBe("Meeting Notes");
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
