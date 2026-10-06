import { Badge } from "@/components/ui/badge";
import type { AuditEvent, AuditOutcome } from "@/lib/types";

const outcomes = {
  requested: { label: "Requested", style: "bg-blue-50 text-blue-700" },
  succeeded: { label: "Succeeded", style: "bg-green-50 text-green-800" },
  failed: { label: "Failed", style: "bg-red-50 text-red-800" },
  unknown: { label: "Unknown", style: "bg-slate-100 text-slate-700" },
};

export function OutcomeBadge({ outcome }: { outcome: AuditOutcome }) {
  const value = outcomes[outcome] ?? outcomes.unknown;
  return <Badge variant="secondary" className={`rounded-full text-[11.5px] font-semibold ${value.style}`}>{value.label}</Badge>;
}

export const actionLabels: Record<string, string> = {
  "recording.import": "Recording import",
  "recording.retry": "Recording retry",
  "recording.cancel": "Recording cancellation",
  "recording.reprocess": "Recording reprocess",
  "recording.processing": "Recording processing",
  "email.approval_requested": "Email approval requested",
  "email.approved": "Email approved",
  "email.send": "Email submission",
};

export function actorLabel(event: AuditEvent) {
  return event.actor_type === "system" ? ({ recording_worker: "Recording worker", email_sender: "Email sender" }[event.actor_id] ?? event.actor_id) : event.actor_upn ?? event.actor_id;
}

const tokens: Record<string, readonly string[]> = {
  source: ["manual", "manual_retry", "manual_reprocess", "webhook", "calendar_processing", "reconcile"],
  previous_state: ["pending", "processing", "failed", "cancelled", "completed"],
  new_state: ["pending", "processing", "failed", "cancelled", "completed"],
  error_category: ["processing_error", "interrupted", "attempts_exhausted", "reprocess_conflict"],
  reason: ["lease_expired", "existing_result_preserved"],
};

export function safeMetadata(metadata: AuditEvent["metadata"]) {
  return Object.entries(metadata ?? {}).filter(([key, value]) => {
    if (key === "retry_scheduled") return typeof value === "boolean";
    if (key === "attempt" || key === "recipient_count") return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 2147483647;
    if (key === "parent_job_id") return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
    return typeof value === "string" && Array.isArray(tokens[key]) && tokens[key].includes(value);
  });
}
