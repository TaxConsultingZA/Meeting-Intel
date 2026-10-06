"""Read/control the existing recording queue. No cross-user processing grants."""
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_, exists, func
from sqlalchemy.orm import selectinload, load_only, raiseload

from ..config import get_settings
from ..db import get_db
from ..models import RecordingJob, Meeting, MeetingParticipant, ActionItem, ProcessingState, RegisteredUser
from ..services.job_control import RETRYABLE_JOB_STATES, public_job_error
from ..services.access import NO_VIEW_ACCESS_TYPES
from ..services.jobs import enqueue_retry_job
from ..services.audit import add_audit_event
from ..services.status_diagnostics import RecordingStatusRoute, response_ready
from ..services.reprocessing import (
    MANUAL_REPROCESS_SOURCE,
    is_clean_reprocess_candidate,
    is_meeting_organizer,
)
from .deps import registered_user

router = APIRouter(route_class=RecordingStatusRoute)


def job_out(job, meeting, upn, is_admin=False, *, clean_candidate=None, organizer=None):
    def clean():
        return clean_candidate if clean_candidate is not None else is_clean_reprocess_candidate(meeting)

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
        and (is_admin or (organizer if organizer is not None else is_meeting_organizer(meeting, upn)))
        and clean()
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
                          and clean())
                ),
                can_reprocess=can_reprocess,
                can_cancel=can_control and job.status in ("pending", "processing") and not job.cancel_requested_at,
                is_stuck=is_stuck,
                processing_enabled=get_settings().recording_processing_enabled)


@router.get("/recordings/jobs")
async def list_jobs(
    meeting_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db=Depends(get_db),
    user: RegisteredUser = Depends(registered_user),
):
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
             .options(
                 load_only(Meeting.id, Meeting.title, Meeting.state, Meeting.organizer_upn, raiseload=True),
                 raiseload("*"),
             ))
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
    rows = (await db.execute(query.order_by(RecordingJob.created_at.desc()).limit(limit))).all()
    # Load large review fields once per meeting, only for controls which need
    # the existing clean-draft check. Ordinary status rows never fetch them.
    organizer_ids = {
        meeting.id for job, meeting in rows
        if meeting is not None and meeting.state == ProcessingState.awaiting_review
        and not user.is_admin and job.status == "completed"
        and job.owner_upn.lower() == upn.lower()
    }
    organizers = {}
    if organizer_ids:
        organizer_meetings = (await db.scalars(select(Meeting).where(Meeting.id.in_(organizer_ids)).options(
            load_only(Meeting.id, Meeting.organizer_upn, raiseload=True),
            selectinload(Meeting.participants).load_only(
                MeetingParticipant.id, MeetingParticipant.user_upn, MeetingParticipant.is_organizer, raiseload=True),
            raiseload("*"),
        ))).all()
        organizers = {meeting.id: is_meeting_organizer(meeting, upn) for meeting in organizer_meetings}
    candidate_ids = {
        meeting.id for job, meeting in rows
        if meeting is not None and meeting.state == ProcessingState.awaiting_review
        and (user.is_admin or job.owner_upn.lower() == upn.lower())
        and ((job.status == "completed" and (user.is_admin or organizers.get(meeting.id, False)))
             or (job.status in ("failed", "cancelled") and job.source == MANUAL_REPROCESS_SOURCE))
    }
    clean_candidates = {}
    if candidate_ids:
        candidates = (await db.scalars(select(Meeting).where(Meeting.id.in_(candidate_ids)).options(
            load_only(Meeting.id, Meeting.state, Meeting.transcript, Meeting.extracted_json,
                      Meeting.approved_by, Meeting.approved_at, Meeting.approved_recipients,
                      Meeting.email_delivery_status, raiseload=True),
            selectinload(Meeting.action_items).load_only(
                ActionItem.id, ActionItem.edited_by, ActionItem.approved, raiseload=True),
            raiseload("*"),
        ))).all()
        clean_candidates = {meeting.id: is_clean_reprocess_candidate(meeting) for meeting in candidates}
    # Include status projection and FastAPI response encoding in serialization.
    response_ready()
    seen = set()
    result = []
    for job, meeting in rows:
        if user.is_admin or job.drive_item_id not in seen:
            seen.add(job.drive_item_id)
            result.append(job_out(job, meeting, upn, user.is_admin,
                                  clean_candidate=clean_candidates.get(meeting.id, False) if meeting else False,
                                  organizer=organizers.get(meeting.id, False) if meeting else False))
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
    new_job_id = uuid4()
    if not await enqueue_retry_job(db, drive_item_id=job.drive_item_id, drive_id=job.drive_id,
                                   owner_upn=job.owner_upn,
                                   commit=False, job_id=new_job_id,
                                   source=MANUAL_REPROCESS_SOURCE if reprocess_job else "manual_retry"):
        await db.rollback()
        raise HTTPException(409, "Recording is already queued or processing")
    add_audit_event(
        db, event_type="recording.retry", outcome="requested",
        actor_type="user", actor_id=str(user.id), actor_upn=user.upn,
        actor_entra_oid=getattr(user, "entra_oid", None), resource_type="recording_job",
        resource_id=new_job_id, job_id=new_job_id,
        meeting_id=meeting.id if meeting else None, correlation_id=new_job_id,
        event_key=f"recording.retry:{new_job_id}",
        metadata={"parent_job_id": str(job.id),
                  "source": MANUAL_REPROCESS_SOURCE if reprocess_job else "manual_retry"},
    )
    await db.commit()
    return {"ok": True, "status": "queued"}


@router.post("/recordings/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, db=Depends(get_db), user: RegisteredUser = Depends(registered_user)):
    job = await controlled_job(db, job_id, user)
    if job.status == "cancelled":
        return {"ok": True, "status": "cancelled"}
    if job.status not in ("pending", "processing"):
        raise HTTPException(409, "Completed or failed jobs cannot be cancelled")
    first_request = job.cancel_requested_at is None
    previous_state = job.status
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
    if first_request:
        add_audit_event(
            db, event_type="recording.cancel", outcome="requested",
            actor_type="user", actor_id=str(user.id), actor_upn=user.upn,
            actor_entra_oid=getattr(user, "entra_oid", None), resource_type="recording_job",
            resource_id=job.id, job_id=job.id, correlation_id=job.id,
            event_key=f"recording.cancel:{job.id}",
            metadata={"previous_state": previous_state, "new_state": job.status},
        )
    await db.commit()
    return {"ok": True, "status": "cancelled" if job.status == "cancelled" else "cancel_requested"}
