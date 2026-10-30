"""Cancellation fences shared by the API, worker and pipeline."""
from contextlib import contextmanager

import httpx
from sqlalchemy import select
from ..ai.contracts import FailureCode
from ..models import RecordingJob
from .recording_audit import add_processing_outcome

RETRYABLE_JOB_STATES = frozenset({"failed", "cancelled"})


class JobCancelled(Exception):
    pass


_FAILURE_STAGES = {"download": "Recording download", "transcription": "Transcription",
                   "extraction": "AI extraction"}
_FAILURE_CATEGORIES = {
    "timeout": "Service timed out", "rate_limited": "Service rate limited",
    "unavailable": "Service unavailable", "access_unavailable": "Access unavailable",
    "configuration": "Service configuration incomplete", "invalid_output": "Unusable processing output",
    "unknown": "Failure reason unavailable",
}


def _failure_message(stage, category):
    return f"{_FAILURE_STAGES[stage]} failed. Category: {_FAILURE_CATEGORIES[category]}."


def processing_failure_info(error, *, cancelled=False):
    """Return only known stage/category tokens; legacy messages do not imply a stage."""
    if cancelled:
        return {"stage": "processing", "category": "cancelled"}
    context = getattr(error, "_safe_processing_failure", None) if isinstance(error, Exception) else None
    if (isinstance(context, tuple) and len(context) == 2
            and all(isinstance(value, str) for value in context)
            and context[0] in _FAILURE_STAGES and context[1] in _FAILURE_CATEGORIES):
        return {"stage": context[0], "category": context[1]}
    if isinstance(error, str):
        for stage in _FAILURE_STAGES:
            for category in _FAILURE_CATEGORIES:
                if error == _failure_message(stage, category):
                    return {"stage": stage, "category": category}
    return None


@contextmanager
def processing_stage(stage):
    """Annotate an unchanged exception with safe context; never alter retry/cancellation."""
    try:
        yield
    except JobCancelled:
        raise
    except Exception as exc:
        category = "unknown"
        code = getattr(exc, "code", None)
        if isinstance(code, FailureCode):
            category = code.value
        elif isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            category = "timeout"
        elif isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            category = ("access_unavailable" if status in {401, 403} else
                        "rate_limited" if status == 429 else
                        "unavailable" if status >= 500 else "unknown")
        elif isinstance(exc, httpx.ConnectError):
            category = "unavailable"
        elif stage == "transcription" and isinstance(exc, ValueError) and str(exc) == "Transcript is empty; extraction cannot proceed":
            category = "invalid_output"
        try:
            exc._safe_processing_failure = (stage, category)
        except (AttributeError, TypeError):
            pass  # An exception which disallows annotations still propagates unchanged.
        raise


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
            add_processing_outcome(db, job, "succeeded")
    await db.commit()


def public_job_error(error):
    """Expose useful categories, never upstream bodies, URLs or credentials."""
    if not error:
        return None
    failure = processing_failure_info(error)
    if failure:
        return _failure_message(failure["stage"], failure["category"])
    value = str(error).lower()
    if "reconciliation" in value or "submission" in value:
        return "Provider submission needs manual verification. Automatic resubmission is blocked."
    if "reprocess conflict" in value:
        return "Reprocess stopped because the meeting was edited or approved. Existing results were kept."
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
