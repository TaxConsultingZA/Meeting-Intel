"""Stage recording outcomes only at durable, caller-owned decision points."""
from .audit import add_audit_event


def add_processing_started(db, job):
    return add_audit_event(
        db, event_type="recording.started", outcome="succeeded",
        actor_type="system", actor_id="recording_worker",
        resource_type="recording_job", resource_id=job.id,
        job_id=job.id, correlation_id=job.id,
        event_key=f"recording.started:{job.id}:{job.attempts}",
        metadata={"attempt": job.attempts, "source": job.source,
                  "previous_state": "pending", "new_state": "processing"},
    )


def add_cancellation_completed(db, job, *, actor=None, meeting_id=None):
    identity = ({"actor_type": "user", "actor_id": str(actor.id),
                 "actor_upn": actor.upn, "actor_entra_oid": getattr(actor, "entra_oid", None)}
                if actor is not None else
                {"actor_type": "system", "actor_id": "recording_worker"})
    return add_audit_event(
        db, event_type="recording.cancelled", outcome="succeeded", **identity,
        resource_type="recording_job", resource_id=job.id,
        job_id=job.id, meeting_id=meeting_id, correlation_id=job.id,
        event_key=f"recording.cancelled:{job.id}:{job.attempts}",
        metadata={"attempt": job.attempts, "new_state": "cancelled"},
    )


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
