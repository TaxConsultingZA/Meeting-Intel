"use client";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import LocalDateTime from "@/components/local-date-time";
import type { AuditEvent } from "@/lib/types";
import { FileText } from "lucide-react";
import { eventTitle, actorLabel, resourceLabel, outcomeDescription, failureDescription, failureStage, recoveryDescription, metadataLabel, metadataValue, OutcomeBadge, safeMetadata } from "./audit-display";

export default function AuditEventDialog({ event }: { event: AuditEvent }) {
  const fields = [
    ["Actor type", event.actor_type], ["Actor ID", event.actor_id],
    ["Event ID", event.id], ["Event type", event.event_type],
    ["Resource type", event.resource_type], ["Resource ID", event.resource_id],
    ["Job ID", event.job_id], ["Meeting ID", event.meeting_id], ["Correlation ID", event.correlation_id],
  ];
  const metadata = safeMetadata(event.metadata).filter(([key]) => key !== "error_category");
  const failure = failureDescription(event);
  return <Dialog>
    <DialogTrigger render={<button type="button" className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-[#dde1e8] bg-white px-2.5 py-1.5 text-[12px] font-semibold text-[#003366] hover:border-[#003366] hover:bg-[#f8fafc] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#003366]" aria-label={`View details for ${event.id}`} />}><FileText size={14} aria-hidden="true" />View details</DialogTrigger>
    <DialogContent showCloseButton={false} className="flex max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden rounded-xl bg-white p-0 sm:max-w-xl">
      <DialogHeader className="bg-[#003366] border-b-4 border-[#C9A52C] px-6 py-4">
        <DialogTitle className="text-white text-[15px] font-semibold">Audit Event Details</DialogTitle>
        <DialogDescription className="text-white/70 text-xs">Historical action and outcome information.</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 min-w-0 max-h-[65vh] overflow-y-auto break-words px-6 py-5 text-[13px]">
        <dl className="space-y-3">
          <div><dt className="text-xs font-medium text-[#6b7280]">Timestamp</dt><dd><LocalDateTime value={event.occurred_at} /><div className="text-xs text-[#6b7280]">{event.occurred_at} (UTC)</div></dd></div>
          <div><dt className="text-xs font-medium text-[#6b7280]">Action</dt><dd className="font-semibold text-[#003366]">{eventTitle(event.event_type)}</dd></div>
          <div><dt className="text-xs font-medium text-[#6b7280]">Actor</dt><dd className="break-words">{actorLabel(event)}</dd></div>
          <div><dt className="text-xs font-medium text-[#6b7280]">Resource</dt><dd>{resourceLabel(event)}<span className="mt-1 block text-xs text-[#6b7280]">Name not provided in this audit event.</span></dd></div>
          <div><dt className="text-xs font-medium text-[#6b7280]">Outcome</dt><dd className="mt-1"><OutcomeBadge outcome={event.outcome} /><p className="mt-2 leading-5">{outcomeDescription(event)}</p></dd></div>
          {event.outcome === "failed" && <div><dt className="text-xs font-medium text-[#6b7280]">Failure stage</dt><dd className="mt-1 leading-5">{failureStage(event)}</dd></div>}
          {failure && <div><dt className="text-xs font-medium text-[#6b7280]">Failure category</dt><dd className="mt-1 leading-5">{failure}</dd></div>}
          {event.outcome === "failed" && <div><dt className="text-xs font-medium text-[#6b7280]">Recovery information</dt><dd className="mt-1 leading-5">{recoveryDescription(event)}</dd></div>}
        </dl>
        <h3 className="mt-5 border-t border-[#dde1e8] pt-3 text-sm font-semibold text-[#003366]">Metadata</h3>
        {metadata.length ? <dl className="mt-2 space-y-2">{metadata.map(([key, value]) => <div key={key}><dt className="text-xs text-[#6b7280]">{metadataLabel(key)}</dt><dd className="break-words">{metadataValue(key, value)}</dd></div>)}</dl> : <p className="mt-2 text-xs text-[#6b7280]">No additional metadata.</p>}
        <details className="mt-5 border-t border-[#dde1e8] pt-3">
          <summary className="cursor-pointer text-sm font-semibold text-[#003366]">Technical details</summary>
          <dl className="mt-3 space-y-3">{fields.map(([label, value]) => <div key={label}><dt className="text-xs font-medium text-[#6b7280]">{label}</dt><dd className="break-all">{value ?? "—"}</dd></div>)}</dl>
        </details>
      </div>
      <DialogFooter className="m-0 border-[#dde1e8] bg-[#f8fafc] px-6 py-3">
        <DialogClose render={<Button variant="outline" className="rounded-md border-[#dde1e8] text-[#003366]" />}>Close</DialogClose>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
