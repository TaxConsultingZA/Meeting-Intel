from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from ..config import get_settings
from ..db import get_db
from ..models import ProcessedItem, RecordingJob, Meeting, ProcessingState, RegisteredUser
from ..graph import client as graph
from ..services.jobs import enqueue_recording_job, enqueue_retry_job
from ..services.job_control import public_job_error
from ..services.reprocessing import (
    MANUAL_REPROCESS_SOURCE,
    is_clean_reprocess_candidate,
    is_meeting_organizer,
)
from .deps import registered_user, require_subscribed

settings = get_settings()
router = APIRouter()


class ImportRequest(BaseModel):
    drive_item_id: str
    drive_id: str


async def _verify_owned_drive_item(upn: str, drive_id: str, drive_item_id: str) -> dict:
    """Verify tenant-wide Graph identifiers against the signed-in user's drive."""
    try:
        owned_drive_id = await graph.get_user_drive_id(upn)
        if drive_id != owned_drive_id:
            raise HTTPException(403, "Recording does not belong to your OneDrive")
        item = await graph.get_drive_item(owned_drive_id, drive_item_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Could not verify OneDrive recording: {exc}") from exc

    if item.get("id") and item["id"] != drive_item_id:
        raise HTTPException(403, "Recording identity could not be verified")
    if not str(item.get("name", "")).lower().endswith(".mp4"):
        raise HTTPException(422, "Only MP4 recordings can be processed")
    return item


@router.get("/recordings/available")
async def available_recordings(
    db: AsyncSession = Depends(get_db),
    upn: str = Depends(require_subscribed),
):
    """List recordings from the durable OneDrive reconciliation state."""
    user = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    drive_ids = set(await db.scalars(
        select(RecordingJob.drive_id).where(RecordingJob.owner_upn == upn)
    ))
    if user and user.graph_drive_id:
        drive_ids.add(user.graph_drive_id)
    if not drive_ids:
        return []

    ledgers = list(await db.scalars(
        select(ProcessedItem).where(ProcessedItem.drive_id.in_(drive_ids))
    ))
    if not ledgers:
        return []
    item_ids = [row.drive_item_id for row in ledgers]

    meetings_by_item: dict[str, Meeting] = {}
    rows = await db.scalars(select(Meeting).where(Meeting.drive_item_id.in_(item_ids)))
    for m in rows.all():
        meetings_by_item[m.drive_item_id] = m
    job_item_ids = set(await db.scalars(
        select(RecordingJob.drive_item_id).where(RecordingJob.drive_item_id.in_(item_ids))
    ))

    result = []
    for ledger in ledgers:
        iid = ledger.drive_item_id
        m = meetings_by_item.get(iid)
        result.append({
            "drive_item_id": iid,
            "drive_id": ledger.drive_id,
            "name": m.title if m and m.title else ledger.filename or "Unknown",
            "size": None,
            "created_at": m.recorded_at.isoformat() if m and m.recorded_at else None,
            "already_imported": iid in job_item_ids or m is not None,
            "meeting_id": str(m.id) if m else None,
            "meeting_state": m.state if m else None,
            "meeting_error": public_job_error(m.error) if m else None,
        })
    return result


@router.post("/recordings/import")
async def import_recording(
    req: ImportRequest,
    db: AsyncSession = Depends(get_db),
    upn: str = Depends(require_subscribed),
):
    """Trigger background processing of a new recording."""
    item = await _verify_owned_drive_item(upn, req.drive_id, req.drive_item_id)
    ledger = await db.scalar(
        select(ProcessedItem).where(ProcessedItem.drive_item_id == req.drive_item_id)
    )
    if ledger:
        prior_job = await db.scalar(
            select(RecordingJob.id).where(RecordingJob.drive_item_id == req.drive_item_id).limit(1)
        )
        queued = False if prior_job else await enqueue_retry_job(
            db, drive_item_id=req.drive_item_id, drive_id=req.drive_id,
            owner_upn=upn, source="manual",
        )
    else:
        queued = await enqueue_recording_job(
            db,
            drive_item_id=req.drive_item_id,
            drive_id=req.drive_id,
            owner_upn=upn,
            source="manual",
            etag=item.get("eTag"),
            filename=item.get("name"),
        )
    if not queued:
        raise HTTPException(status_code=409, detail="Already imported or currently processing")
    return {"ok": True, "queued": True}


@router.post("/recordings/reprocess")
async def reprocess_recording(
    req: ImportRequest,
    db: AsyncSession = Depends(get_db),
    user: RegisteredUser = Depends(registered_user),
):
    """Queue a fresh transcription for an untouched completed review draft."""
    if not getattr(user, "is_admin", False) and not getattr(user, "is_subscribed", True):
        raise HTTPException(403, "Subscribe before accessing Calendar or OneDrive")
    return await _queue_reprocess(db, req.drive_item_id, user)


@router.post("/recordings/jobs/{job_id}/reprocess")
async def reprocess_recording_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: RegisteredUser = Depends(registered_user),
):
    """Queue the existing safe reprocess workflow from a known completed job."""
    job = await db.scalar(select(RecordingJob).where(RecordingJob.id == job_id))
    if not job:
        raise HTTPException(404, "Recording job not found")
    actor_upn = getattr(user, "upn", user)
    if job.owner_upn.lower() != actor_upn.lower() and not getattr(user, "is_admin", False):
        raise HTTPException(403, "Only the recording owner can reprocess this recording")
    return await _queue_reprocess(db, job.drive_item_id, user, job)


async def _queue_reprocess(
    db: AsyncSession,
    drive_item_id: str,
    user: RegisteredUser,
    source_job: RecordingJob | None = None,
):
    upn = getattr(user, "upn", user)
    m = await db.scalar(
        select(Meeting)
        .where(Meeting.drive_item_id == drive_item_id)
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
        .with_for_update()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Meeting record not found")
    if m.state in (ProcessingState.approved, ProcessingState.sent):
        raise HTTPException(status_code=409, detail="Approved or sent meeting results cannot be reprocessed")
    if m.state != ProcessingState.awaiting_review:
        raise HTTPException(status_code=409, detail=f"Cannot reprocess: review state is {m.state.value}")

    if not getattr(user, "is_admin", False) and not is_meeting_organizer(m, upn):
        raise HTTPException(403, "Only the meeting organiser can reprocess this recording")
    if not is_clean_reprocess_candidate(m):
        raise HTTPException(409, "Meeting results were edited or cannot be verified as untouched")

    ledger = await db.scalar(
        select(ProcessedItem).where(ProcessedItem.drive_item_id == drive_item_id)
    )
    if not ledger or not ledger.drive_id:
        raise HTTPException(409, "Original recording drive is unavailable")
    owner_upn = source_job.owner_upn if source_job else upn
    await _verify_owned_drive_item(owner_upn, ledger.drive_id, drive_item_id)
    completed_job = source_job or await db.scalar(
        select(RecordingJob.id).where(
            RecordingJob.drive_item_id == drive_item_id,
            RecordingJob.status == "completed",
        ).limit(1)
    )
    if not completed_job or (source_job is not None and source_job.status != "completed"):
        raise HTTPException(409, "A completed recording job could not be verified")

    queued = await enqueue_retry_job(
        db,
        drive_item_id=drive_item_id,
        drive_id=ledger.drive_id,
        owner_upn=owner_upn,
        source=MANUAL_REPROCESS_SOURCE,
    )
    if not queued:
        await db.rollback()
        raise HTTPException(409, "Recording is already queued or processing")
    return {"ok": True, "queued": True}
