"""Read-only projections. Unknown evidence is null, never inferred from attempts."""
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from ..models import RecordingJob, AuditEvent
from .audit_queries import _aware, safe_metadata
from .job_control import processing_failure_info


def project_job(job, events):
    # Stable event keys identify facts. Neither refresh nor repeated read adds usage.
    events = list({event.event_key: event for event in events}.values())
    accepted = [e for e in events if e.event_type == "provider.submitted" and e.outcome == "succeeded"]
    # Current persisted provider ID is acceptance evidence for legacy jobs too.
    confirmed = 1 if accepted or job.provider_transcript_id else None
    starts = [e for e in events if e.event_type == "recording.started"
              and (e.event_metadata or {}).get("attempt") == job.attempts]
    ends = [e for e in events if e.event_type in {"recording.processing", "recording.cancelled"}
            and (e.event_metadata or {}).get("attempt") == job.attempts
            and (e.event_metadata or {}).get("new_state") in {"completed", "failed", "cancelled"}]
    duration = None
    if len(starts) == len(ends) == 1:
        delta = (_aware(ends[0].occurred_at) - _aware(starts[0].occurred_at)).total_seconds()
        if delta >= 0:
            duration = delta
    usage = []
    for e in events:
        metadata = safe_metadata(e.event_metadata)
        if e.event_type in {"ai.extraction_completed", "ai.extraction_failed"} and "total_tokens" in metadata:
            usage.append({"event_id": str(e.id), "occurred_at": e.occurred_at,
                          **{k: metadata[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in metadata}})
    audio = job.audio_duration_seconds
    if type(audio) not in (int, float) or not math.isfinite(audio) or audio < 0:
        audio = None
    return dict(job_id=job.id, status=job.status, attempts=job.attempts,
                created_at=job.created_at, confirmed_submissions=confirmed,
                submission_evidence="accepted_event" if accepted else "persisted_provider_id" if confirmed else "unknown",
                submission_uncertain=job.provider_status in {"submitting", "submission_unknown"},
                provider_status=job.provider_status if job.provider_status in {
                    "submitting", "submission_unknown", "submitted", "queued", "processing", "completed", "error", "poll_unknown"} else None,
                audio_duration_seconds=audio, token_usage=usage,
                ai_submissions_with_reported_usage=len(usage) if usage else None,
                processing_duration_seconds=duration,
                failure=processing_failure_info(job.last_error, cancelled=job.status == "cancelled") if job.status in {"failed", "cancelled"} else None,
                actual_cost=None, estimated_cost=None, cost_status="unknown")


async def query_processing_monitor(db, *, job_id=None, recording_id=None, status=None, start=None, end=None):
    end = _aware(end) if end is not None else datetime.now(timezone.utc)
    start = _aware(start) if start is not None else end - timedelta(days=7)
    if start >= end or end - start > timedelta(days=90):
        raise ValueError("Invalid date range")
    query = select(RecordingJob).where(RecordingJob.created_at >= start, RecordingJob.created_at < end)
    for column, value in ((RecordingJob.id, job_id), (RecordingJob.drive_item_id, recording_id), (RecordingJob.status, status)):
        if value is not None:
            query = query.where(column == value)
    jobs = list((await db.scalars(query.order_by(RecordingJob.created_at.desc(), RecordingJob.id.desc()).limit(51))).all())
    has_more = len(jobs) > 50
    jobs = jobs[:50]
    # Event aggregation is independent of the display time window; do not turn partial
    # history into a false zero. All events remain in the existing audit table.
    events = list((await db.scalars(select(AuditEvent).where(AuditEvent.job_id.in_([j.id for j in jobs])))).all()) if jobs else []
    by_job = {}
    for event in events:
        by_job.setdefault(event.job_id, []).append(event)
    return dict(items=[project_job(j, by_job.get(j.id, [])) for j in jobs], has_more=has_more,
                window_start=start, window_end=end)
