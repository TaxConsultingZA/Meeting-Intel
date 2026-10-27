"""Owner-controlled display associations; never rewrite processing or access history."""
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ProcessedItem, RecordingJob
from app.graph import client as graph
from app.services.meeting_matching import recording_datetime, event_people


def display_identity(ledger, metadata=None, recorded_at=None):
    """Keep Teams evidence separate from a stable Outlook event association.

    Evidence must be bound to this exact file, not just a similar title/time.
    This read model never edits results, participants or associations.
    """
    identity = ledger.identity_json or {}
    event = identity.get("event") or {}
    metadata = metadata or {}
    linked = bool(event.get("id")) and identity.get("status") == "linked"
    if not identity:
        legacy = metadata.get("t5_calendar_event") or {}
        linked = bool(metadata.get("outlook_event_id") or (legacy.get("id") if isinstance(legacy, dict) else None))
    teams = identity.get("teams_meeting") or {}
    verified = bool(
        teams.get("verified") is True and teams.get("meeting_id")
        and teams.get("recording_reference") and teams.get("title")
        and teams.get("drive_id") == ledger.drive_id
        and teams.get("drive_item_id") == ledger.drive_item_id
    )
    reason = None
    if not linked:
        if identity.get("status") == "needs_review":
            reason = "Previous calendar association is unverified; saved results are preserved."
        elif verified:
            reason = "Teams meeting verified; no verified Outlook event ID."
        elif not identity.get("recorded_at") and not recorded_at:
            reason = "Recording time unavailable; meeting identity cannot be confirmed."
        else:
            reason = "No unique calendar event with matching title, time and owner evidence."
    return {"calendar_matched": linked, "teams_meeting_verified": verified,
            "teams_meeting_title": teams.get("title") if verified else None,
            "identity_reason": reason}


async def owned_recording(db, user, drive_id, item_id, *, lock=False):
    # Verify against Microsoft, not a client-supplied owner or historical title.
    try:
        owned_drive = await graph.get_user_drive_id(user.upn)
    except Exception:
        raise HTTPException(502, "Unable to verify recording owner") from None
    if owned_drive != drive_id:
        raise HTTPException(403, "Only the recording owner may change its calendar link")
    query = select(ProcessedItem).where(ProcessedItem.drive_id == drive_id,
                                      ProcessedItem.drive_item_id == item_id)
    if lock:
        query = query.with_for_update()
    ledger = await db.scalar(query)
    if ledger is None:
        raise HTTPException(404, "Discovered recording not found")
    return ledger


async def file_metadata(drive_id, item_id):
    try:
        item = await graph.get_drive_item(drive_id, item_id)
    except Exception:
        raise HTTPException(502, "Unable to read recording metadata; check existing file access") from None
    parent_drive = (item.get("parentReference") or {}).get("driveId")
    if (item.get("id") != item_id or item.get("folder") is not None or item.get("deleted")
            or item.get("remoteItem") or (parent_drive and parent_drive != drive_id)
            or not str(item.get("name", "")).lower().endswith(".mp4")):
        raise HTTPException(422, "Recording identity could not be verified")
    return item


async def calendar_choices(db, user, drive_id, item_id):
    await owned_recording(db, user, drive_id, item_id)
    item = await file_metadata(drive_id, item_id)
    instant = recording_datetime(item["name"], item)
    if instant is None:
        raise HTTPException(409, "Recording time is unavailable; keep it independent")
    try:
        events = await graph.get_calendar_window(user.upn, instant-timedelta(days=2), instant+timedelta(days=2))
    except Exception:
        raise HTTPException(502, "Unable to read your calendar; keep the recording independent or retry") from None
    return [event_snapshot(e) for e in events
            if e.get("id") and user.upn.lower() in event_people(e)[0]]


def event_snapshot(event):
    return {k: event.get(k) for k in ("id", "iCalUId", "subject", "start", "end", "isCancelled")}


async def choose_association(db, user, drive_id, item_id, event_id):
    ledger = await owned_recording(db, user, drive_id, item_id, lock=True)
    active = await db.scalar(select(RecordingJob.id).where(
        RecordingJob.drive_item_id == item_id, RecordingJob.status.in_(("pending", "processing"))).limit(1))
    if active:
        raise HTTPException(409, "Wait for active recording processing to finish")
    item = await file_metadata(drive_id, item_id)
    event = None
    if event_id:
        # The submitted stable ID must also be among this owner's bounded choices.
        choices = await calendar_choices(db, user, drive_id, item_id)
        event = next((e for e in choices if e["id"] == event_id), None)
        if event is None:
            raise HTTPException(422, "Select an event from your recording's calendar choices")
    instant = recording_datetime(item["name"], item)
    ledger.filename = item["name"]
    ledger.identity_json = {
        "status": "linked" if event else "independent",
        "event": event, "recorded_at": instant.isoformat() if instant else None,
        "size": item.get("size"), "decided_by": user.upn,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    return ledger
