import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ActionLoading from "../../action-items/loading";
import SearchLoading from "../loading";
import ActionError from "../../action-items/error";
import SearchError from "../error";
import RootLoading from "../../loading";

const path = vi.hoisted(() => ({ current: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => path.current }));

afterEach(() => { cleanup(); path.current = "/"; });
it.each([["/action-items", "Action Items"], ["/search", "Search saved meetings"]])("selects the destination even in the parent loading boundary", (pathname, title) => {
  path.current = pathname;
  render(<RootLoading />);
  expect(screen.getByRole("heading", { name: title })).toBeVisible();
  expect(screen.queryByText("Meeting Intelligence")).not.toBeInTheDocument();
});
it("retains the existing Dashboard loading UI on the home route", () => {
  render(<RootLoading />);
  expect(screen.getByRole("heading", { name: "Meeting Intelligence" })).toBeVisible();
});
it.each([[ActionLoading, "Action Items"], [SearchLoading, "Search saved meetings"]] as const)("renders the target loading shell, never Dashboard content", (Loading, title) => {
  render(<Loading />);
  expect(screen.getByRole("heading", { name: title })).toBeVisible();
  expect(screen.getByRole("link", { name: title })).toHaveAttribute("aria-current", "page");
  expect(screen.queryByText("Meeting Intelligence")).not.toBeInTheDocument();
  expect(screen.queryByText("Upcoming Meetings")).not.toBeInTheDocument();
  expect(screen.queryByText("View meetings on Dashboard")).not.toBeInTheDocument();
});
it.each([[ActionError, "Action Items"], [SearchError, "Search saved meetings"]] as const)("offers route-level recovery with the target navigation", (ErrorPage, title) => {
  const retry = vi.fn();
  render(<ErrorPage error={new Error("private upstream details")} retry={retry} />);
  expect(screen.getByRole("heading", { name: title })).toBeVisible();
  expect(screen.queryByText("private upstream details")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(retry).toHaveBeenCalledOnce();
});
