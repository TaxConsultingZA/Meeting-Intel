import { cn } from "@/lib/utils";
import type { ProcessingState } from "@/lib/types";

const CONFIG: Record<ProcessingState, { label: string; cls: string; dot: string }> = {
  queued:          { label: "Queued",          cls: "bg-blue-50 text-blue-700",   dot: "bg-blue-400" },
  downloading:     { label: "Downloading",     cls: "bg-blue-50 text-blue-700",   dot: "bg-blue-500 animate-pulse" },
  transcribing:    { label: "Transcribing",    cls: "bg-blue-50 text-blue-700",   dot: "bg-blue-500 animate-pulse" },
  extracting:      { label: "Extracting",      cls: "bg-blue-50 text-blue-700",   dot: "bg-blue-500 animate-pulse" },
  awaiting_review: { label: "Awaiting Review", cls: "bg-amber-50 text-amber-800", dot: "bg-amber-400" },
  approved:        { label: "Approved",        cls: "bg-green-50 text-green-800", dot: "bg-green-500" },
  sent:            { label: "Sent",            cls: "bg-green-50 text-green-700", dot: "bg-green-400" },
  failed:          { label: "Failed",          cls: "bg-red-50 text-red-800",     dot: "bg-red-500" },
  cancelled:       { label: "Cancelled",       cls: "bg-gray-100 text-gray-700", dot: "bg-gray-400" },
  cancel_requested:{ label: "Cancel requested",cls: "bg-amber-50 text-amber-800", dot: "bg-amber-400 animate-pulse" },
  processing:      { label: "Processing",      cls: "bg-blue-50 text-blue-700", dot: "bg-blue-500 animate-pulse" },
  completed:       { label: "Completed",       cls: "bg-green-50 text-green-800", dot: "bg-green-500" },
};

export default function StateBadge({ state }: { state: ProcessingState }) {
  const c = CONFIG[state] ?? CONFIG.queued;
  return (
    <span className={cn("inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11.5px] font-semibold", c.cls)}>
      <span className={cn("w-1.5 h-1.5 rounded-full", c.dot)} />
      {c.label}
    </span>
  );
}
