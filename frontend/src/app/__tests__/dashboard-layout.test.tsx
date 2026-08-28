import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import DashboardClient from "../dashboard-client";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/api", () => ({
  getAllMeetings: vi.fn(), requestHistoricalAccess: vi.fn(),
  shareMeeting: vi.fn(), unsubscribeCurrentUser: vi.fn(),
}));
// A mounted panel must be detectable even when the real component has no jobs.
vi.mock("@/components/recording-jobs", () => ({
  default: () => <section aria-label="Recording processing">Recording processing</section>,
}));
vi.mock("@/components/import-modal", () => ({
  default: () => <div role="dialog" aria-label="Process Past Recording">Recording import</div>,
}));

afterEach(cleanup);

it("keeps the dashboard stats, meeting tabs and import entry without the persistent job panel", () => {
  render(<DashboardClient meetings={[]} upcoming={[]} historical={[]}
    upn="reviewer@example.test" accessToken="offline-test-token"
    isSubscribed={true} syncStates={[]} loadErrors={[]} />);

  for (const label of ["Upcoming", "In Progress", "Awaiting Review", "Completed"]) {
    expect(screen.getAllByRole("button", { name: new RegExp(label) }).length).toBeGreaterThan(0);
  }
  expect(screen.getByRole("button", { name: "Old Meetings" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Recording processing" })).not.toBeInTheDocument();
  expect(screen.queryByText("Recording processing")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Process Past Recording" }));
  expect(screen.getByRole("dialog", { name: "Process Past Recording" })).toBeInTheDocument();
});
