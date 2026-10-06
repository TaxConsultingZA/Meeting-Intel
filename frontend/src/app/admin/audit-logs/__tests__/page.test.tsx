import { expect, it, beforeEach, vi } from "vitest";
const mocks = vi.hoisted(() => ({ auth: vi.fn(), me: vi.fn(), redirect: vi.fn() }));
vi.mock("@/lib/auth", () => ({ auth: mocks.auth }));
vi.mock("@/lib/api", () => ({ getMe: mocks.me }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("@/components/nav", () => ({ default: () => null }));
vi.mock("../audit-logs-client", () => ({ default: () => null }));
import AuditLogsPage from "../page";
beforeEach(() => {
  vi.resetAllMocks();
  mocks.redirect.mockImplementation((path) => { throw new Error(`redirect:${path}`); });
  mocks.auth.mockResolvedValue({ user: { email: "admin@example.test" }, accessToken: "token" });
});
it("redirects missing and expired sessions to login", async () => {
  mocks.auth.mockResolvedValueOnce(null);
  await expect(AuditLogsPage()).rejects.toThrow("redirect:/login");
  mocks.auth.mockResolvedValueOnce({ user: { email: "admin@example.test" }, accessToken: "token", authError: "expired" });
  await expect(AuditLogsPage()).rejects.toThrow("redirect:/login");
  expect(mocks.me).not.toHaveBeenCalled();
});
it("denies members and unregistered users", async () => {
  mocks.me.mockResolvedValueOnce({ is_admin: false }).mockResolvedValueOnce(null);
  await expect(AuditLogsPage()).rejects.toThrow("redirect:/");
  await expect(AuditLogsPage()).rejects.toThrow("redirect:/");
});
it("allows existing admins without a subscription requirement", async () => {
  mocks.me.mockResolvedValue({ is_admin: true, is_subscribed: false });
  expect(await AuditLogsPage()).toBeTruthy();
  expect(mocks.me).toHaveBeenCalledWith("token");
});
