import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db, SessionLocal
from ..models import ProcessedItem, Meeting, MeetingParticipant, ProcessingState
from ..graph import client as graph
from ..services.ledger import claim_item
from ..pipeline.steps import process_recording
from .deps import require_subscribed

settings = get_settings()
router = APIRouter()


class ImportRequest(BaseModel):
    drive_item_id: str
    drive_id: str


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
        raise HTTPException(status_code=502, detail=f"Could not reach OneDrive: {e}")

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
            "meeting_error": m.error if m else None,
        })
    return result


@router.post("/recordings/import")
async def import_recording(
    req: ImportRequest,
    db: AsyncSession = Depends(get_db),
    upn: str = Depends(require_subscribed),
):
    """Trigger background processing of a new recording."""
    claimed = await claim_item(db, req.drive_item_id, req.drive_id, etag=None, source="manual")
    if not claimed:
        raise HTTPException(status_code=409, detail="Already imported or currently processing")

    async def _run() -> None:
        async with SessionLocal() as session:
            await process_recording(session, req.drive_item_id, req.drive_id, owner_upn=upn)

    asyncio.create_task(_run())
    return {"ok": True}


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

    if not any(p.user_upn == upn for p in m.participants):
        db.add(MeetingParticipant(meeting_id=m.id, user_upn=upn, is_organizer=False))

    m.state = ProcessingState.queued
    m.error = None
    await db.commit()

    async def _run() -> None:
        async with SessionLocal() as session:
            await process_recording(session, req.drive_item_id, req.drive_id, owner_upn=upn)

    asyncio.create_task(_run())
    return {"ok": True}
