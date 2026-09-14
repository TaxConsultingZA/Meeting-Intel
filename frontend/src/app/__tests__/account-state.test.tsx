import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import DashboardPage from "../page";
import { getMe } from "@/lib/api";

vi.mock("@/lib/auth", () => ({
  auth: vi.fn().mockResolvedValue({
    user: { email: "wei.jiuyang@taxconsulting.co.za" },
    accessToken: "token",
  }),
}));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("@/lib/api", () => ({ getMe: vi.fn() }));
vi.mock("@/components/pending-access", () => ({
  default: () => <div>Access Pending</div>,
}));
vi.mock("@/components/nav", () => ({ default: () => null }));
vi.mock("@/components/subscription-gate", () => ({ default: () => null }));
vi.mock("../dashboard-client", () => ({ default: () => null }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("shows Access Pending for the explicit unregistered account result", async () => {
  vi.mocked(getMe).mockResolvedValue(null);
  render(await DashboardPage());
  expect(screen.getByText("Access Pending")).toBeInTheDocument();
});

it.each(["platform 404", "backend 5xx or network failure"])(
  "shows an account service error for %s",
  async () => {
    vi.mocked(getMe).mockRejectedValue(new Error("Unable to reach backend"));
    render(await DashboardPage());
    expect(screen.getByRole("alert")).toHaveTextContent("Service unavailable");
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to load account");
    expect(screen.queryByText("Access Pending")).not.toBeInTheDocument();
  },
);
