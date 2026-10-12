"""Content-free extraction events; persistence uses the caller's existing fence."""
from uuid import NAMESPACE_URL, uuid4, uuid5

from ..ai.contracts import FailureCode
from .audit import add_audit_event
from .job_control import JobCancelled, processing_stage


async def audited_extraction(db, *, meeting_id, job_id, lease_token, commit,
                             extract, segments, **kwargs):
    # A worker lease identifies one attempt. Direct/test calls get a fresh run ID.
    run_id = (uuid5(NAMESPACE_URL, f"meeting-intel:extraction:{job_id}:{lease_token}")
              if lease_token is not None else uuid4())

    def stage(action, outcome, error_category=None):
        metadata = {}
        if error_category is not None:
            metadata["error_category"] = error_category
        add_audit_event(
            db, event_type=f"ai.extraction_{action}", outcome=outcome,
            actor_type="system", actor_id="recording_worker",
            resource_type="meeting", resource_id=meeting_id,
            meeting_id=meeting_id, job_id=job_id, correlation_id=job_id or run_id,
            event_key=f"ai.extraction_{action}:{meeting_id}:{run_id}",
            metadata=metadata,
        )

    stage("requested", "requested")
    await commit()  # Durable before invocation, without holding the job lock during AI.
    try:
        with processing_stage("extraction"):
            result = await extract(meeting_id, segments, **kwargs)
    except JobCancelled:
        raise
    except Exception as exc:
        # Never persist exception text or arbitrary provider attributes.
        code = getattr(exc, "code", None)
        category = code.value if isinstance(code, FailureCode) else "unknown"
        stage("failed", "failed", category)
        await commit()
        raise
    # asyncio cancellation propagates without a false failure event.
    stage("completed", "succeeded")
    await commit()  # No success from a superseded/cancelled worker.
    return result
