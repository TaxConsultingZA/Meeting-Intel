import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import TaskCompletionControl from "../task-completion";
import { ApiError, setTaskCompletion } from "@/lib/api";
import type { TaskCompletion } from "@/lib/types";

vi.mock("@/lib/api", async () => ({ ...await vi.importActual<typeof import("@/lib/api")>("@/lib/api"), setTaskCompletion: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const item = { id: "task", task: "Send report", can_complete: true, completed_at: null };
function Harness() {
  const [value, setValue] = useState<TaskCompletion>(item);
  return <TaskCompletionControl item={{ ...item, ...value }} token="token" onUpdate={setValue} />;
}

it("completes and reopens using server metadata", async () => {
  vi.mocked(setTaskCompletion).mockResolvedValueOnce({ completed_at: "2026-10-15T09:00:00Z", completed_by_id: "user", can_complete: true })
    .mockResolvedValueOnce({ completed_at: null, completed_by_id: null, can_complete: true });
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Mark complete: Send report" }));
  fireEvent.click(await screen.findByRole("button", { name: "Reopen: Send report" }));
  expect(await screen.findByRole("button", { name: "Mark complete: Send report" })).toBeEnabled();
  expect(setTaskCompletion).toHaveBeenNthCalledWith(1, "task", true, "token");
  expect(setTaskCompletion).toHaveBeenNthCalledWith(2, "task", false, "token");
});

it("blocks duplicate clicks and retains state after an unconfirmed request", async () => {
  let reject!: (error: Error) => void;
  vi.mocked(setTaskCompletion).mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
  render(<Harness />);
  const button = screen.getByRole("button", { name: "Mark complete: Send report" });
  fireEvent.click(button); fireEvent.click(button);
  expect(button).toBeDisabled();
  expect(setTaskCompletion).toHaveBeenCalledTimes(1);
  reject(new Error("timeout"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not confirm task status");
  expect(screen.getByText("Open")).toBeVisible();
  await waitFor(() => expect(button).toBeEnabled());
});

it("displays revoked authority safely", async () => {
  vi.mocked(setTaskCompletion).mockRejectedValue(new ApiError(403, "secret"));
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Mark complete: Send report" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("no longer have permission");
  expect(screen.queryByText(/secret/)).not.toBeInTheDocument();
});

it("shows status without controls to viewers", () => {
  render(<TaskCompletionControl item={{ ...item, can_complete: false }} token="token" onUpdate={vi.fn()} />);
  expect(screen.getByText("Open")).toBeVisible();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
