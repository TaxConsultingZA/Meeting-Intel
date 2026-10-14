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
  "recording.reprocess": "Recording reprocessing",
  "recording.processing": "Recording processing",
  "recording.started": "Recording processing started",
  "recording.cancelled": "Recording cancellation completed",
  "ai.extraction_requested": "AI extraction requested",
  "ai.extraction_completed": "AI extraction completed",
  "ai.extraction_failed": "AI extraction failed",
  "email.approval_requested": "Email approval requested",
  "email.approved": "Review approved",
  "email.send": "Email submission",
};

export function eventTitle(eventType: string) {
  return actionLabels[eventType] ?? "Other audit event";
}

export function resourceLabel(event: AuditEvent) {
  return ({ meeting: "Meeting", recording_job: "Recording job" }[event.resource_type] ?? "Resource");
}

export function outcomeDescription(event: AuditEvent) {
  if (event.event_type === "email.send") {
    if (event.outcome === "succeeded") return "Microsoft Graph accepted the email request. Delivery is not confirmed.";
    if (event.outcome === "unknown") return "Email submission could not be confirmed. Check delivery before resending.";
  }
  if (event.outcome === "requested") return "Request recorded. Completion is not confirmed by this event.";
  if (event.outcome === "failed") return "This action failed. Review the available failure details.";
  if (event.outcome === "unknown") return "The outcome could not be confirmed.";
  if (event.event_type === "email.approved") return "Meeting notes were approved. This event does not confirm email delivery.";
  if (event.event_type === "recording.started") return "Recording processing started. Completion is recorded separately.";
  if (event.event_type === "recording.cancelled") return "Recording processing was cancelled.";
  return "This action completed successfully.";
}

const failureLabels: Record<string, string> = {
  processing_error: "Recording processing could not be completed.",
  interrupted: "Processing was interrupted.",
  attempts_exhausted: "The processing attempt limit was reached.",
  reprocess_conflict: "Meeting results changed during reprocessing. Replacement was blocked.",
  timeout: "The processing service timed out.",
  rate_limited: "The service temporarily limited requests.",
  unavailable: "The processing service was unavailable.",
  configuration: "Service configuration is incomplete.",
  invalid_output: "The processing output could not be used.",
  connection_unavailable: "A connection to the email service could not be established.",
  provider_rejected: "The email service rejected the request.",
  submission_uncertain: "Email submission could not be confirmed.",
  unknown: "The failure category is unknown.",
};

export function failureDescription(event: AuditEvent) {
  const category = safeMetadata(event.metadata).find(([key]) => key === "error_category")?.[1];
  if (typeof category === "string") return failureLabels[category] ?? "Failure category unavailable.";
  return event.outcome === "failed" ? "No failure category was provided." : null;
}

// The stage labels describe recorded event types, never a guessed root cause.
export function failureStage(event: AuditEvent) {
  const stages: Record<string, string> = {
    "recording.import": "Recording import",
    "recording.retry": "Recording retry",
    "recording.cancel": "Recording cancellation",
    "recording.reprocess": "Recording reprocessing",
    "recording.processing": "Recording processing",
    "ai.extraction_failed": "AI extraction",
    "email.approval_requested": "Email approval",
    "email.approved": "Review approval",
    "email.send": "Email submission",
  };
  return Object.hasOwn(stages, event.event_type) ? stages[event.event_type] : "Stage not provided in this audit event.";
}

export function recoveryDescription(event: AuditEvent) {
  const metadata = Object.fromEntries(safeMetadata(event.metadata));
  const information: string[] = [];
  if (metadata.retry_scheduled === true) information.push("Retry scheduled.");
  if (metadata.retry_scheduled === false) information.push("No retry scheduled by this event.");
  if (metadata.reason === "existing_result_preserved") information.push("Previously saved meeting results were preserved.");
  return information.length ? information.join(" ") : "No recovery information was provided.";
}

export function metadataLabel(key: string) {
  return ({ source: "Source", previous_state: "Previous status", new_state: "New status",
    error_category: "Failure category", reason: "Explanation", retry_scheduled: "Retry scheduled",
    attempt: "Processing attempt", recipient_count: "Recipient count", parent_job_id: "Previous job ID" }[key] ?? "Additional detail");
}

export function metadataValue(key: string, value: string | number | boolean | null) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value !== "string") return String(value);
  if (key === "error_category") return failureLabels[value] ?? "Failure category unavailable.";
  if (key === "source") return ({ manual: "Manual import", manual_retry: "Manual retry", manual_reprocess: "Manual reprocessing",
    webhook: "Recording notification", calendar_processing: "Calendar processing", reconcile: "Scheduled recording sync" }[value] ?? "Source unavailable");
  if (key === "reason") return ({ lease_expired: "The worker did not renew its processing lease in time.",
    existing_result_preserved: "Previously saved meeting results were preserved." }[value] ?? "Explanation unavailable");
  if (key === "previous_state" || key === "new_state") return ({ pending: "Queued", processing: "Processing",
    failed: "Failed", cancelled: "Cancelled", completed: "Completed" }[value] ?? "Status unavailable");
  return value;
}

export function actorLabel(event: AuditEvent) {
  return event.actor_type === "system" ? ({ recording_worker: "Recording worker", email_sender: "Email sender" }[event.actor_id] ?? event.actor_id) : event.actor_upn ?? event.actor_id;
}

const tokens: Record<string, readonly string[]> = {
  source: ["manual", "manual_retry", "manual_reprocess", "webhook", "calendar_processing", "reconcile"],
  previous_state: ["pending", "processing", "failed", "cancelled", "completed"],
  new_state: ["pending", "processing", "failed", "cancelled", "completed"],
  error_category: ["processing_error", "interrupted", "attempts_exhausted", "reprocess_conflict", "timeout", "rate_limited", "unavailable", "configuration", "invalid_output", "unknown", "connection_unavailable", "provider_rejected", "submission_uncertain"],
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
