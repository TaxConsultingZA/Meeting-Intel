import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Nav from "../nav";
vi.mock("next/navigation", () => ({ usePathname: () => "/admin/audit-logs" }));
vi.mock("next-auth/react", () => ({ signOut: vi.fn() }));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("../notification-bell", () => ({ default: () => null }));
afterEach(() => { cleanup(); });
it("keeps Admin active on the nested audit route", () => {
  render(<Nav userEmail="admin@example.test" accessToken="token" isAdmin />);
  expect(screen.getByRole("link", { name: "Admin" })).toHaveClass("text-[#C9A52C]");
  expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveClass("text-[#C9A52C]");
});
it("does not expose Admin navigation to members", () => {
  render(<Nav userEmail="member@example.test" accessToken="token" />);
  expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
});
