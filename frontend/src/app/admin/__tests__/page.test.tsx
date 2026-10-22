import { beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ auth: vi.fn(), me: vi.fn(), redirect: vi.fn() }));
vi.mock("@/lib/auth", () => ({ auth: mocks.auth }));
vi.mock("@/lib/api", () => ({ getMe: mocks.me }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("@/components/nav", () => ({ default: () => null }));
vi.mock("../admin-client", () => ({ default: () => null }));
import AdminPage from "../page";

beforeEach(() => {
  vi.resetAllMocks();
  mocks.redirect.mockImplementation(path => { throw new Error(`redirect:${path}`); });
  mocks.auth.mockResolvedValue({ user: { email: "admin@example.test" }, accessToken: "token" });
});
it("allows existing administrators to open the monitoring page", async () => {
  mocks.me.mockResolvedValue({ is_admin: true });
  expect(await AdminPage()).toBeTruthy();
  expect(mocks.me).toHaveBeenCalledWith("token");
  expect(mocks.redirect).not.toHaveBeenCalled();
});
it("denies non-administrators and unregistered users", async () => {
  mocks.me.mockResolvedValueOnce({ is_admin: false }).mockResolvedValueOnce(null);
  await expect(AdminPage()).rejects.toThrow("redirect:/");
  await expect(AdminPage()).rejects.toThrow("redirect:/");
});
it("requires a valid authenticated session", async () => {
  mocks.auth.mockResolvedValueOnce(null).mockResolvedValueOnce({
    user: { email: "admin@example.test" }, accessToken: "token", authError: "expired",
  });
  await expect(AdminPage()).rejects.toThrow("redirect:/login");
  await expect(AdminPage()).rejects.toThrow("redirect:/login");
  expect(mocks.me).not.toHaveBeenCalled();
});
