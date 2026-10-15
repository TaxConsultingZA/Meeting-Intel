import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import PipelineView from "../pipeline-view";
import { recordingStatusMessage } from "@/components/recording-jobs";
import type { RecordingJobOut } from "@/lib/types";

afterEach(cleanup);
const queued: RecordingJobOut = {
  job_id: "job", drive_item_id: "recording", meeting_id: "meeting", title: "Meeting",
  status: "pending", processing_status: "queued", phase: "queued", review_status: null,
  attempts: 0, max_attempts: 3, error: null, can_retry: false, can_cancel: true,
  can_reprocess: false, processing_enabled: false,
};

it("matches the sidebar's paused message without animated processing", () => {
  const { container } = render(<PipelineView state="queued" job={queued} />);
  expect(screen.getByRole("heading", { name: "Processing paused" })).toBeVisible();
  expect(screen.getByText(recordingStatusMessage(queued))).toBeVisible();
  expect(container.querySelector(".animate-spin")).toBeNull();
  expect(screen.queryByText(/being processed|Check back shortly|AssemblyAI/)).not.toBeInTheDocument();
});

it("keeps active cancellation pending even when new processing is disabled", () => {
  const job = { ...queued, status: "processing", processing_status: "cancel_requested" as const };
  render(<PipelineView state="transcribing" job={job} />);
  expect(screen.getByRole("heading", { name: "Cancellation pending" })).toBeVisible();
  expect(screen.getByText(recordingStatusMessage(job))).toBeVisible();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
  expect(screen.queryByText(/Processing cancelled|Processing paused/)).not.toBeInTheDocument();
});

it("uses provider-neutral wording for confirmed transcription", () => {
  const job = { ...queued, status: "processing", processing_status: "transcribing" as const, processing_enabled: true };
  render(<PipelineView state="transcribing" job={job} />);
  expect(screen.getByText(recordingStatusMessage(job))).toBeVisible();
  expect(screen.getByText("Creating a speaker-labelled transcript")).toBeVisible();
  expect(screen.queryByText(/AssemblyAI/)).not.toBeInTheDocument();
});

it("does not guess progress while job status is unavailable", () => {
  render(<PipelineView state="queued" />);
  expect(screen.getByText(/Recording progress is not yet confirmed/)).toBeVisible();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
  expect(screen.queryByText(/being processed|Check back shortly/)).not.toBeInTheDocument();
});
