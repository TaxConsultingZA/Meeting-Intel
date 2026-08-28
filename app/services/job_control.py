"""Cancellation fences shared by the API, worker and pipeline."""
from sqlalchemy import select
from ..models import RecordingJob


class JobCancelled(Exception):
    pass


async def guarded_commit(db, job_id=None, lease_token=None, *, complete=False):
    if job_id is not None:
        with db.no_autoflush:
            job = await db.scalar(select(RecordingJob).where(
                RecordingJob.id == job_id, RecordingJob.lease_token == lease_token,
                RecordingJob.status == "processing", RecordingJob.cancel_requested_at.is_(None),
            ).with_for_update().execution_options(populate_existing=True))
        if job is None:
            await db.rollback()
            raise JobCancelled("Cancellation requested or recording lease lost")
        if complete:
            job.status = "completed"
            job.locked_at = None
            job.lease_token = None
            job.last_error = None
    await db.commit()


def public_job_error(error):
    """Expose useful categories, never upstream bodies, URLs or credentials."""
    if not error:
        return None
    value = str(error).lower()
    if "cancel" in value:
        return "Recording processing was cancelled. Saved meeting data has been kept."
    if "disabled" in value or "configuration" in value or "api_key" in value:
        return "Processing is disabled or its service configuration is incomplete. Contact an administrator."
    if "403" in value or "permission" in value or "forbidden" in value:
        return "The recording service could not access the source. Check your OneDrive permissions."
    if "429" in value or "rate limit" in value:
        return "The processing service is rate limited. Retry later."
    if "timeout" in value or "timed out" in value:
        return "The processing service timed out. You can retry this recording."
    if "lease" in value or "stopped" in value or "interrupted" in value:
        return "Processing was interrupted. Saved transcript data has been kept for retry."
    if "transcript is empty" in value:
        return "No usable transcript was returned for this recording."
    return "Recording processing failed. Saved data has been kept; retry or contact an administrator."
