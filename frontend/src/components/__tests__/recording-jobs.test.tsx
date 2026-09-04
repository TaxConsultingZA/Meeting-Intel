import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import StateBadge from "../state-badge";
import { JobControls } from "../recording-jobs";
import type { ProcessingState, RecordingJobOut } from "@/lib/types";
import { cancelRecordingJob, retryRecordingJob } from "@/lib/api";

vi.mock("@/lib/api", () => ({ cancelRecordingJob: vi.fn(), retryRecordingJob: vi.fn(), getRecordingJobs: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const job: RecordingJobOut = { job_id: "job", drive_item_id: "item", meeting_id: "meeting", title: "Meeting", status: "failed", processing_status: "failed", review_status: null, phase: "failed", attempts: 3, max_attempts: 3, error: null, can_retry: true, can_cancel: false, processing_enabled: false };

describe("recording job controls", () => {
  it.each<[ProcessingState, string]>([["queued", "Queued"], ["downloading", "Downloading"], ["transcribing", "Transcribing"], ["extracting", "Extracting"], ["awaiting_review", "Awaiting Review"], ["completed", "Completed"], ["failed", "Failed"], ["cancelled", "Cancelled"], ["cancel_requested", "Cancel requested"]])("renders %s truthfully", (state, label) => {
    render(<StateBadge state={state} />); expect(screen.getByText(label)).toBeInTheDocument();
  });
  it("hides controls when the backend denies ownership", () => {
    render(<JobControls job={{ ...job, can_retry: false }} token="token" onChanged={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("retries through the existing job ID and refreshes", async () => {
    vi.mocked(retryRecordingJob).mockResolvedValue({ ok: true, status: "queued" });
    const changed = vi.fn(); render(<JobControls job={job} token="token" onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(changed).toHaveBeenCalledOnce());
    expect(retryRecordingJob).toHaveBeenCalledWith("job", "token");
  });
  it("requests cancellation without pretending it completed", async () => {
    vi.mocked(cancelRecordingJob).mockResolvedValue({ ok: true, status: "cancel_requested" });
    const changed = vi.fn(); render(<JobControls job={{ ...job, status: "processing", processing_status: "transcribing", phase: "transcribing", can_retry: false, can_cancel: true }} token="token" onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(changed).toHaveBeenCalledOnce());
    expect(cancelRecordingJob).toHaveBeenCalledWith("job", "token");
  });
  it("does not repeat cancel after cancellation is requested", () => {
    render(<JobControls job={{ ...job, status: "processing", processing_status: "cancel_requested", phase: "cancel_requested", can_retry: false, can_cancel: false }} token="token" onChanged={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });
});
