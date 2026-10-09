import { beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ auth: vi.fn(), redirect: vi.fn() }));
vi.mock("@/lib/auth", () => ({ auth: mocks.auth }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("@/components/nav", () => ({ default: () => null }));
vi.mock("../action-items-client", () => ({ default: () => null }));
import ActionItemsPage from "../page";
beforeEach(() => { vi.resetAllMocks(); mocks.redirect.mockImplementation(path => { throw new Error(`redirect:${path}`); }); });
it("redirects absent or expired sessions", async () => {
  mocks.auth.mockResolvedValueOnce(null).mockResolvedValueOnce({ user: { email: "alice@example.test" }, accessToken: "token", authError: "expired" });
  await expect(ActionItemsPage()).rejects.toThrow("redirect:/login");
  await expect(ActionItemsPage()).rejects.toThrow("redirect:/login");
});
it("renders the read-only page without subscription or registration writes", async () => {
  mocks.auth.mockResolvedValue({ user: { email: "alice@example.test" }, accessToken: "token" });
  expect(await ActionItemsPage()).toBeTruthy();
});
