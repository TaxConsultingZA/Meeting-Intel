from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import ProcessedItem, Meeting, ProcessingState
from ..graph import client as graph
from ..services.jobs import enqueue_recording_job, enqueue_retry_job
from ..services.sync_state import record_sync_result
from ..services.job_control import public_job_error
from .deps import require_subscribed

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
    """List recordings in the user's OneDrive Recordings folder with current processing state."""
    try:
        drive_id = await graph.get_user_drive_id(upn)
        items = await graph.list_recordings_folder(drive_id)
    except Exception as e:
        await record_sync_result(db, user_upn=upn, source="onedrive", error=e)
        raise HTTPException(status_code=502, detail=f"Could not reach OneDrive: {e}")
    await record_sync_result(db, user_upn=upn, source="onedrive")

    if not items:
        return []

    item_ids = [i["id"] for i in items]

    already = set(
        await db.scalars(
            select(ProcessedItem.drive_item_id).where(
                ProcessedItem.drive_item_id.in_(item_ids)
            )
        )
    )

    meetings_by_item: dict[str, Meeting] = {}
    if already:
        rows = await db.scalars(
            select(Meeting).where(Meeting.drive_item_id.in_(already))
        )
        for m in rows.all():
            meetings_by_item[m.drive_item_id] = m

    result = []
    for item in items:
        iid = item["id"]
        m = meetings_by_item.get(iid)
        result.append({
            "drive_item_id": iid,
            "drive_id": drive_id,
            "name": item.get("name", "Unknown"),
            "size": item.get("size"),
            "created_at": item.get("createdDateTime"),
            "already_imported": iid in already,
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
    queued = await enqueue_recording_job(
        db,
        drive_item_id=req.drive_item_id,
        drive_id=req.drive_id,
        owner_upn=upn,
        source="manual",
        etag=item.get("eTag"),
    )
    if not queued:
        raise HTTPException(status_code=409, detail="Already imported or currently processing")
    return {"ok": True, "queued": True}


@router.post("/recordings/reprocess")
async def reprocess_recording(
    req: ImportRequest,
    db: AsyncSession = Depends(get_db),
    upn: str = Depends(require_subscribed),
):
    """Re-trigger processing for a failed recording and ensure caller is a participant."""
    m = await db.scalar(
        select(Meeting)
        .where(Meeting.drive_item_id == req.drive_item_id)
        .options(selectinload(Meeting.participants))
    )
    if not m:
        raise HTTPException(status_code=404, detail="Meeting record not found")
    if m.state not in (ProcessingState.failed, ProcessingState.queued):
        raise HTTPException(status_code=409, detail=f"Cannot reprocess: state is {m.state}")

    is_organizer = (m.organizer_upn or "").lower() == upn or any(
        p.user_upn.lower() == upn and p.is_organizer for p in m.participants
    )
    if not is_organizer:
        raise HTTPException(403, "Only the meeting organiser can reprocess this recording")

    ledger = await db.scalar(
        select(ProcessedItem).where(ProcessedItem.drive_item_id == req.drive_item_id)
    )
    if not ledger or not ledger.drive_id:
        raise HTTPException(409, "Original recording drive is unavailable")
    await _verify_owned_drive_item(upn, ledger.drive_id, req.drive_item_id)

    m.state = ProcessingState.queued
    m.error = None
    await db.flush()
    queued = await enqueue_retry_job(
        db,
        drive_item_id=req.drive_item_id,
        drive_id=ledger.drive_id,
        owner_upn=upn,
    )
    if not queued:
        await db.rollback()
        raise HTTPException(409, "Recording is already queued or processing")
    return {"ok": True, "queued": True}
