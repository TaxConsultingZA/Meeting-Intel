import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import StateBadge from "../state-badge";
import RecordingJobs, { JobControls } from "../recording-jobs";
import type { ProcessingState, RecordingJobOut } from "@/lib/types";
import { toast } from "sonner";
import { cancelRecordingJob, getRecordingJobs, retryRecordingJob, reprocessRecordingJob } from "@/lib/api";

vi.mock("@/lib/api", () => ({ cancelRecordingJob: vi.fn(), retryRecordingJob: vi.fn(), getRecordingJobs: vi.fn(), reprocessRecordingJob: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const job: RecordingJobOut = { job_id: "job", drive_item_id: "item", meeting_id: "meeting", title: "Meeting", status: "failed", processing_status: "failed", review_status: null, phase: "failed", attempts: 3, max_attempts: 3, error: null, can_retry: true, can_cancel: false, can_reprocess: false, processing_enabled: false };

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
  it("shows loading feedback while recording status is being fetched", () => {
    vi.mocked(getRecordingJobs).mockReturnValue(new Promise(() => {}));
    render(<RecordingJobs token="token" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading recording status");
  });
  it("shows no retry control for completed and allows cancelled retry", () => {
    const { rerender } = render(<JobControls job={{ ...job, status: "completed", processing_status: "completed", phase: "completed", can_retry: false, can_cancel: false }} token="token" onChanged={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    rerender(<JobControls job={{ ...job, status: "cancelled", processing_status: "cancelled", phase: "cancelled", can_retry: true, can_cancel: false }} token="token" onChanged={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});


describe("recording recovery feedback", () => {
  it("blocks duplicate requests and identifies the active action", async () => {
    let finish!: (value: { ok: boolean; status: string }) => void;
    vi.mocked(retryRecordingJob).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    render(<JobControls job={job} token="token" onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    const pending = screen.getByRole("button", { name: "Queuing retry…" });
    expect(pending).toBeDisabled();
    fireEvent.click(pending);
    expect(retryRecordingJob).toHaveBeenCalledOnce();
    finish({ ok: true, status: "queued" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled());
  });
  it.each(["retry", "cancel", "reprocess"] as const)("gives safe guidance when %s fails", async action => {
    vi.mocked(retryRecordingJob).mockRejectedValue(new Error("SQL internal secret"));
    vi.mocked(cancelRecordingJob).mockRejectedValue(new Error("SQL internal secret"));
    vi.mocked(reprocessRecordingJob).mockRejectedValue(new Error("SQL internal secret"));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<JobControls job={{ ...job, can_retry: action === "retry", can_cancel: action === "cancel", can_reprocess: action === "reprocess" }} token="token" showReprocess onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Refresh the status before trying again")));
    expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining("SQL"));
    vi.restoreAllMocks();
  });
  it("distinguishes accepted requests from refresh failures", async () => {
    vi.mocked(retryRecordingJob).mockResolvedValue({ ok: true, status: "queued" });
    render(<JobControls job={job} token="token" onChanged={async () => { throw new Error("refresh"); }} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Your request was accepted")));
    expect(toast.success).toHaveBeenCalledOnce();
  });
  it("does not mislabel an unknown status as queued", () => {
    render(<StateBadge state={"unknown" as ProcessingState} />);
    expect(screen.getByText("Status unavailable")).toBeInTheDocument();
  });
  it("provides a next step after a loading failure", async () => {
    vi.mocked(getRecordingJobs).mockRejectedValue(new Error("internal"));
    render(<RecordingJobs token="token" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Refresh to try again");
    expect(screen.getByRole("button", { name: "Refresh status" })).toBeEnabled();
  });
});

describe("recording lifecycle visibility", () => {
  it.each<[RecordingJobOut["processing_status"], string, string]>([
    ["queued", "pending", "Queued"],
    ["processing", "processing", "Processing"],
    ["downloading", "processing", "Processing"],
    ["extracting", "processing", "Processing"],
    ["transcribing", "processing", "Transcribing"],
    ["completed", "completed", "Completed"],
    ["failed", "failed", "Failed"],
    ["cancelled", "cancelled", "Cancelled"],
    ["cancel_requested", "processing", "Processing"],
  ])("shows the lifecycle for %s without changing review status", async (processing_status, status, label) => {
    vi.mocked(getRecordingJobs).mockResolvedValue([{ ...job, status, processing_status, review_status: "awaiting_review", can_retry: false }]);
    render(<RecordingJobs token="token" />);
    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByText("Awaiting Review")).toBeInTheDocument();
    expect(screen.getByText("Processing attempts: 3 of 3")).toBeInTheDocument();
    if (processing_status === "cancel_requested") {
      expect(screen.getByText("Cancellation pending")).toBeInTheDocument();
      expect(screen.queryByText("Cancelled")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    }
    if (processing_status === "downloading") expect(screen.getByText(/Preparing the recording/)).toBeInTheDocument();
    if (processing_status === "extracting") expect(screen.getByText(/Preparing meeting notes/)).toBeInTheDocument();
  });

  it("offers reprocess only when the existing backend capability allows it", async () => {
    vi.mocked(getRecordingJobs).mockResolvedValue([{ ...job, status: "completed", processing_status: "completed", can_retry: false, can_reprocess: true }]);
    vi.mocked(reprocessRecordingJob).mockResolvedValue({ ok: true, queued: true });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    try {
      render(<RecordingJobs token="token" />);
      fireEvent.click(await screen.findByRole("button", { name: "Reprocess" }));
      await waitFor(() => expect(reprocessRecordingJob).toHaveBeenCalledWith("job", "token"));
      expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    } finally { confirm.mockRestore(); }
  });

  it("refreshes a terminal job and keeps denied recovery actions hidden", async () => {
    vi.mocked(getRecordingJobs).mockResolvedValue([{ ...job, can_retry: false }]);
    render(<RecordingJobs token="token" />);
    await screen.findByText("Failed");
    expect(screen.queryByRole("button", { name: /^(Retry|Reprocess|Cancel)$/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await waitFor(() => expect(getRecordingJobs).toHaveBeenCalledTimes(2));
  });

  it("shows delay guidance from the existing worker status without claiming failure", async () => {
    vi.mocked(getRecordingJobs).mockResolvedValue([{ ...job, status: "processing", processing_status: "transcribing", is_stuck: true, can_retry: false, can_cancel: true }]);
    render(<RecordingJobs token="token" />);
    expect(await screen.findByText(/Processing may be delayed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });

  it("describes a queued automatic retry without labelling the current job failed", async () => {
    vi.mocked(getRecordingJobs).mockResolvedValue([{ ...job, status: "pending", processing_status: "queued", can_retry: false, error: "An earlier attempt timed out", processing_enabled: true }]);
    render(<RecordingJobs token="token" />);
    expect(await screen.findByText("Queued")).toBeInTheDocument();
    expect(screen.getByText(/queued for another attempt/)).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });
});
