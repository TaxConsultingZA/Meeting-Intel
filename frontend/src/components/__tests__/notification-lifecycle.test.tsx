import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import NotificationBell from "../notification-bell";
import { getNotifications } from "@/lib/api";

vi.mock("@/lib/api", () => ({ getNotifications: vi.fn() }));

function visibility(value: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, value });
}

beforeEach(() => {
  vi.useFakeTimers();
  visibility("visible");
  vi.mocked(getNotifications).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
  visibility("visible");
});

it("skips notification requests while hidden and resumes at the next visible tick", async () => {
  render(<NotificationBell upn="test-token" />);
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(getNotifications).toHaveBeenCalledTimes(1);
  visibility("hidden");
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(getNotifications).toHaveBeenCalledTimes(1);
  visibility("visible");
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(getNotifications).toHaveBeenCalledTimes(2);
});

it("does not fetch on a hidden mount or after unmount", async () => {
  visibility("hidden");
  const view = render(<NotificationBell upn="test-token" />);
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(getNotifications).not.toHaveBeenCalled();
  view.unmount();
  visibility("visible");
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(getNotifications).not.toHaveBeenCalled();
});

it("clears both initial and recurring timers when immediately unmounted", async () => {
  const view = render(<NotificationBell upn="test-token" />);
  view.unmount();
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(getNotifications).not.toHaveBeenCalled();
});
