import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SearchPage from "@/app/search/page";
import ActionItemsPage from "@/app/action-items/page";
const { getMe } = vi.hoisted(() => ({ getMe: vi.fn() }));
vi.mock("@/lib/auth", () => ({ auth: async () => ({ user: { email: "wei@example.test" }, accessToken: "token" }) }));
vi.mock("@/lib/api", () => ({ getMe }));
vi.mock("next/navigation", () => ({ usePathname: () => "/search", redirect: vi.fn() }));
vi.mock("next-auth/react", () => ({ signOut: vi.fn() }));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("../notification-bell", () => ({ default: () => null }));
vi.mock("@/app/search/search-client", () => ({ default: () => null }));
vi.mock("@/app/action-items/action-items-client", () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
for (const [name, Page] of [["Search", SearchPage], ["Action Items", ActionItemsPage]] as const) {
  it(`${name} passes the authenticated administrator role to navigation`, async () => {
    getMe.mockResolvedValue({ is_admin: true });
    render(await Page());
    expect(getMe).toHaveBeenCalledWith("token");
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin");
  });
  it.each([false, null, "error"])(`${name} hides Admin for a member or unavailable identity: %s`, async (role) => {
    if (role === "error") getMe.mockRejectedValue(new Error("unavailable"));
    else getMe.mockResolvedValue(role === null ? null : { is_admin: role });
    render(await Page());
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });
}
