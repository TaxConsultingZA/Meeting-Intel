"""Read/control the existing recording queue. No cross-user processing grants."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, exists, func

from ..config import get_settings
from ..db import get_db
from ..models import RecordingJob, Meeting, MeetingParticipant, ProcessingState
from ..services.job_control import public_job_error
from ..services.jobs import enqueue_retry_job
from .deps import require_registered

router = APIRouter()


def job_out(job, meeting, upn):
    processing_status = job.status
    if job.status == "pending":
        processing_status = "queued"
    elif job.status == "processing":
        processing_status = "cancel_requested" if job.cancel_requested_at else (
            meeting.state.value if meeting and meeting.state in (
                ProcessingState.downloading, ProcessingState.transcribing, ProcessingState.extracting,
            ) else "processing")
    review_status = meeting.state.value if job.status == "completed" and meeting and meeting.state in (
        ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent,
    ) else None
    owner = job.owner_upn.lower() == upn.lower()
    return dict(job_id=str(job.id), drive_item_id=job.drive_item_id,
                meeting_id=str(meeting.id) if meeting else None,
                title=meeting.title if meeting else "Recording queued for import",
                status=job.status,
                processing_status=processing_status,
                review_status=review_status,
                # Compatibility for older clients; phase is now processing-only.
                phase=processing_status,
                attempts=job.attempts, max_attempts=job.max_attempts,
                error=public_job_error(job.last_error),
                can_retry=owner and job.status == "failed",
                can_cancel=owner and job.status in ("pending", "processing") and not job.cancel_requested_at,
                processing_enabled=get_settings().recording_processing_enabled)


@router.get("/recordings/jobs")
async def list_jobs(meeting_id: UUID | None = None, db=Depends(get_db), upn=Depends(require_registered)):
    participant = exists(select(MeetingParticipant.id).where(
        MeetingParticipant.meeting_id == Meeting.id,
        func.lower(MeetingParticipant.user_upn) == upn.lower(),
    )).correlate(Meeting)
    query = select(RecordingJob, Meeting).outerjoin(Meeting, Meeting.drive_item_id == RecordingJob.drive_item_id).where(
        or_(func.lower(RecordingJob.owner_upn) == upn.lower(), participant))
    if meeting_id:
        query = query.where(Meeting.id == meeting_id)
    rows = (await db.execute(query.order_by(RecordingJob.created_at.desc()).limit(200))).all()
    seen = set()
    result = []
    for job, meeting in rows:
        if job.drive_item_id not in seen:
            seen.add(job.drive_item_id)
            result.append(job_out(job, meeting, upn))
    return result


async def owned_job(db, job_id, upn):
    job = await db.scalar(select(RecordingJob).where(RecordingJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, "Recording job not found")
    if job.owner_upn.lower() != upn.lower():
        raise HTTPException(403, "Only the recording owner can control this job")
    return job


@router.post("/recordings/jobs/{job_id}/retry")
async def retry_job(job_id: UUID, db=Depends(get_db), upn=Depends(require_registered)):
    job = await owned_job(db, job_id, upn)
    if job.status != "failed":
        raise HTTPException(409, "Only failed recording jobs can be retried")
    meeting = await db.scalar(select(Meeting).where(Meeting.drive_item_id == job.drive_item_id))
    if meeting and meeting.state in (ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent):
        raise HTTPException(409, "Meeting is already available for review; it will not be overwritten")
    if meeting:
        meeting.state = ProcessingState.queued
        meeting.error = None
    if not await enqueue_retry_job(db, drive_item_id=job.drive_item_id, drive_id=job.drive_id,
                                   owner_upn=job.owner_upn):
        await db.rollback()
        raise HTTPException(409, "Recording is already queued or processing")
    return {"ok": True, "status": "queued"}


@router.post("/recordings/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, db=Depends(get_db), upn=Depends(require_registered)):
    job = await owned_job(db, job_id, upn)
    if job.status == "cancelled":
        return {"ok": True, "status": "cancelled"}
    if job.status not in ("pending", "processing"):
        raise HTTPException(409, "Completed or failed jobs cannot be cancelled")
    job.cancel_requested_at = job.cancel_requested_at or datetime.now(timezone.utc)
    if job.status == "pending":
        job.status = "cancelled"
        job.lease_token = None
        job.locked_at = None
        job.last_error = public_job_error("cancelled")
        meeting = await db.scalar(select(Meeting).where(Meeting.drive_item_id == job.drive_item_id))
        if meeting and meeting.state not in (ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent):
            meeting.state = ProcessingState.cancelled
            meeting.error = job.last_error
    # A running worker retains its lease until in-flight work has drained.
    await db.commit()
    return {"ok": True, "status": "cancelled" if job.status == "cancelled" else "cancel_requested"}
