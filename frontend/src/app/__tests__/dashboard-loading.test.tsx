import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import Loading from "../loading";

afterEach(cleanup);

it("keeps the Dashboard layout visible while authentication and the account read are pending", () => {
  render(<Loading />);
  expect(screen.getByRole("heading", { name: "Meeting Intelligence" })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Loading Dashboard");
  expect(screen.getByLabelText("Dashboard loading")).toHaveAttribute("aria-busy", "true");
  expect(screen.getByText("Meetings")).toBeVisible();
  expect(screen.getByText("Upcoming Meetings")).toBeVisible();
  expect(screen.getByText("Awaiting Review", { selector: "span" })).toBeVisible();
  expect(screen.getByLabelText("Meeting cards loading")).toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
