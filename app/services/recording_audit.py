"""Stage recording outcomes only at durable, caller-owned decision points."""
from .audit import add_audit_event


def add_processing_outcome(db, job, outcome, *, meeting_id=None,
                           reason=None, error_category=None, exhausted=False):
    metadata = {
        "source": job.source,
        "attempt": job.attempts,
        "previous_state": "pending" if exhausted else "processing",
        "new_state": job.status,
        "retry_scheduled": job.status == "pending",
    }
    if reason is not None:
        metadata["reason"] = reason
    if error_category is not None:
        metadata["error_category"] = error_category
    suffix = "exhausted" if exhausted else outcome
    return add_audit_event(
        db, event_type="recording.processing", outcome=outcome,
        actor_type="system", actor_id="recording_worker",
        resource_type="recording_job", resource_id=job.id,
        job_id=job.id, meeting_id=meeting_id, correlation_id=job.id,
        event_key=f"recording.processing:{job.id}:{job.attempts}:{suffix}",
        metadata=metadata,
    )
