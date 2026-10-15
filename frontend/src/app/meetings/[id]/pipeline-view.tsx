import { Check, Loader2 } from "lucide-react";
import type { ProcessingState, RecordingJobOut } from "@/lib/types";
import { recordingStatusMessage } from "@/components/recording-jobs";

const STEPS: { state: ProcessingState; label: string; detail: string }[] = [
  { state: "queued",       label: "Recording Detected",   detail: "New file found in OneDrive Recordings folder" },
  { state: "downloading",  label: "Downloading",          detail: "Streaming MP4 from SharePoint to processing environment" },
  { state: "transcribing", label: "Transcribing",         detail: "Creating a speaker-labelled transcript" },
  { state: "extracting",   label: "Processing / Extracting", detail: "Preparing transcript and configured extraction results for review" },
];

const ORDER: ProcessingState[] = ["queued", "downloading", "transcribing", "extracting"];

export default function PipelineView({ state, job }: { state: ProcessingState; job?: RecordingJobOut | null }) {
  const jobIdx = ORDER.findIndex(step => step === job?.processing_status);
  const currentIdx = jobIdx >= 0 ? jobIdx : ORDER.indexOf(state);
  const cancellationPending = job?.processing_status === "cancel_requested";
  const paused = job?.processing_status === "queued" && !job.processing_enabled;
  const title = cancellationPending ? "Cancellation pending" : paused ? "Processing paused" : "Recording processing";
  const message = job ? recordingStatusMessage(job)
    : "Recording progress is not yet confirmed. Check the recording processing panel for the latest status.";
  const showSteps = job && !cancellationPending && ["queued", "downloading", "transcribing", "extracting", "processing"].includes(job.processing_status);

  return (
    <div className="max-w-lg mx-auto mt-6">
      <div className="bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
        <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-6 py-5">
          <h2 className="text-white font-semibold text-[15px]">{title}</h2>
          <p className="text-white/60 text-[13px] mt-1">
            {message}
          </p>
        </div>
        {showSteps && <div className="px-6 py-7">
          <ol className="flex flex-col gap-0">
            {STEPS.map((step, i) => {
              const done   = i < currentIdx;
              const active = i === currentIdx;
              const last   = i === STEPS.length - 1;

              return (
                <li key={step.state} className="flex gap-4 relative pb-7 last:pb-0">
                  {!last && (
                    <span
                      className={`absolute left-4 top-8 w-0.5 h-[calc(100%-8px)] ${done ? "bg-green-500" : "bg-[#dde1e8]"}`}
                    />
                  )}
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 z-10 text-sm font-bold ${
                      done   ? "bg-green-500 text-white" :
                      active ? "bg-[#003366] text-[#C9A52C] border-2 border-[#C9A52C]" :
                               "bg-[#dde1e8] text-[#6b7280]"
                    }`}
                  >
                    {done   ? <Check size={14} /> :
                     active && !paused ? <Loader2 size={14} className="animate-spin" /> :
                              i + 1}
                  </div>
                  <div className="pt-1">
                    <p className={`text-[14px] font-semibold ${active ? "text-[#1a1a2e]" : done ? "text-[#1a1a2e]" : "text-[#9ca3af]"}`}>
                      {step.label}
                    </p>
                    <p className="text-[12.5px] text-[#6b7280] mt-0.5">{step.detail}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>}
      </div>
    </div>
  );
}
