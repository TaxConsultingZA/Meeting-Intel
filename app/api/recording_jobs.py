"""Read/control the existing recording queue. No cross-user processing grants."""
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, exists, func
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import get_db
from ..models import RecordingJob, Meeting, MeetingParticipant, ProcessingState, RegisteredUser
from ..services.job_control import RETRYABLE_JOB_STATES, public_job_error
from ..services.access import NO_VIEW_ACCESS_TYPES
from ..services.jobs import enqueue_retry_job
from ..services.reprocessing import (
    MANUAL_REPROCESS_SOURCE,
    is_clean_reprocess_candidate,
    is_meeting_organizer,
)
from .deps import registered_user

router = APIRouter()


def job_out(job, meeting, upn, is_admin=False):
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
    can_control = owner or is_admin
    reprocess_job = getattr(job, "source", None) == MANUAL_REPROCESS_SOURCE
    is_stuck = bool(
        job.status == "processing" and job.locked_at
        and job.locked_at < datetime.now(timezone.utc) - timedelta(seconds=get_settings().worker_lease_seconds)
    )
    can_reprocess = (
        can_control and job.status == "completed" and meeting is not None
        and (is_admin or is_meeting_organizer(meeting, upn))
        and is_clean_reprocess_candidate(meeting)
    )
    return dict(job_id=str(job.id), drive_item_id=job.drive_item_id,
                meeting_id=str(meeting.id) if meeting else None,
                title=meeting.title if meeting else "Recording queued for import",
                owner_upn=job.owner_upn if is_admin else None,
                status=job.status,
                processing_status=processing_status,
                review_status=review_status,
                # Compatibility for older clients; phase is now processing-only.
                phase=processing_status,
                attempts=job.attempts, max_attempts=job.max_attempts,
                error=public_job_error(job.last_error),
                can_retry=can_control and job.status in ("failed", "cancelled") and (
                    not meeting or meeting.state not in (
                        ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent,
                    ) or (reprocess_job and meeting.state == ProcessingState.awaiting_review
                          and is_clean_reprocess_candidate(meeting))
                ),
                can_reprocess=can_reprocess,
                can_cancel=can_control and job.status in ("pending", "processing") and not job.cancel_requested_at,
                is_stuck=is_stuck,
                processing_enabled=get_settings().recording_processing_enabled)


@router.get("/recordings/jobs")
async def list_jobs(meeting_id: UUID | None = None, db=Depends(get_db), user: RegisteredUser = Depends(registered_user)):
    upn = user.upn
    participant = exists(select(MeetingParticipant.id).where(
        MeetingParticipant.meeting_id == Meeting.id,
        func.lower(MeetingParticipant.user_upn) == upn.lower(),
        MeetingParticipant.access_type.notin_(NO_VIEW_ACCESS_TYPES),
    )).correlate(Meeting)
    owner_can_see_meeting = or_(
        Meeting.id.is_(None),
        func.lower(Meeting.organizer_upn) == upn.lower(),
        participant,
    )
    query = (select(RecordingJob, Meeting)
             .outerjoin(Meeting, Meeting.drive_item_id == RecordingJob.drive_item_id)
             .options(selectinload(Meeting.participants), selectinload(Meeting.action_items)))
    if not user.is_admin:
        # The recording owner may still see an unassociated queue row, or a
        # meeting they own/are an approved participant of. Never leak a linked
        # meeting's metadata merely because the submitter owns the recording.
        query = query.where(or_(
            (func.lower(RecordingJob.owner_upn) == upn.lower()) & owner_can_see_meeting,
            participant,
        ))
    if meeting_id:
        query = query.where(Meeting.id == meeting_id)
    rows = (await db.execute(query.order_by(RecordingJob.created_at.desc()).limit(200))).all()
    seen = set()
    result = []
    for job, meeting in rows:
        if user.is_admin or job.drive_item_id not in seen:
            seen.add(job.drive_item_id)
            result.append(job_out(job, meeting, upn, user.is_admin))
    return result


async def controlled_job(db, job_id, user):
    job = await db.scalar(select(RecordingJob).where(RecordingJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, "Recording job not found")
    upn = getattr(user, "upn", user)
    is_admin = getattr(user, "is_admin", False)
    if job.owner_upn.lower() != upn.lower() and not is_admin:
        raise HTTPException(403, "Only the recording owner can control this job")
    return job


@router.post("/recordings/jobs/{job_id}/retry")
async def retry_job(job_id: UUID, db=Depends(get_db), user: RegisteredUser = Depends(registered_user)):
    job = await controlled_job(db, job_id, user)
    if job.status not in RETRYABLE_JOB_STATES:
        raise HTTPException(409, "Only failed or cancelled recording jobs can be retried")
    meeting = await db.scalar(select(Meeting).where(Meeting.drive_item_id == job.drive_item_id)
                              .options(selectinload(Meeting.action_items)))
    reprocess_job = getattr(job, "source", None) == MANUAL_REPROCESS_SOURCE
    if meeting and meeting.state in (ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent):
        if not (reprocess_job and meeting.state == ProcessingState.awaiting_review
                and is_clean_reprocess_candidate(meeting)):
            raise HTTPException(409, "Meeting is already available for review; it will not be overwritten")
    if meeting and not reprocess_job:
        meeting.state = ProcessingState.queued
        meeting.error = None
    if not await enqueue_retry_job(db, drive_item_id=job.drive_item_id, drive_id=job.drive_id,
                                   owner_upn=job.owner_upn,
                                   source=MANUAL_REPROCESS_SOURCE if reprocess_job else "manual_retry"):
        await db.rollback()
        raise HTTPException(409, "Recording is already queued or processing")
    return {"ok": True, "status": "queued"}


@router.post("/recordings/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, db=Depends(get_db), user: RegisteredUser = Depends(registered_user)):
    job = await controlled_job(db, job_id, user)
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
