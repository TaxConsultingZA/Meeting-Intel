from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..models import RegisteredUser, SyncedCalendarEvent
from .deps import registered_user, require_subscribed
from ..services.calendar_sync import CalendarSyncBusy, sync_subscribed_calendars_once
from .recording_processing_requests import EventReference
from ..utils.timezones import parse_graph_datetime, utc_iso

router = APIRouter()


class CalendarSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarSyncResult(BaseModel):
    status: Literal["success", "partial", "failed"]
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    created: int = Field(ge=0)
    updated: int = Field(ge=0)


@router.post("/calendar/sync", response_model=CalendarSyncResult)
async def sync_calendar_now(body: CalendarSyncRequest,
                            user: RegisteredUser = Depends(registered_user)):
    if not user.is_admin or not user.is_subscribed:
        raise HTTPException(403, "A subscribed administrator is required for calendar sync")
    try:
        return await sync_subscribed_calendars_once()
    except CalendarSyncBusy:
        raise HTTPException(409, "Calendar sync is already running. Wait before trying again.") from None
    except Exception:
        raise HTTPException(503, "Calendar sync could not be completed. Check sync status before trying again.") from None


@router.get("/calendar/recent")
async def recent_meetings(db: AsyncSession = Depends(get_db), upn: str = Depends(require_subscribed)):
    from ..services import cross_user_recordings as service
    now = datetime.now(timezone.utc)
    events = list(await db.scalars(
        select(SyncedCalendarEvent.raw).where(
            SyncedCalendarEvent.user_upn == upn,
            SyncedCalendarEvent.ends_at >= now - timedelta(days=30),
            SyncedCalendarEvent.ends_at < now,
        )
    ))
    user = await service.user_by_upn(db, upn)
    recent = [e for e in events if service.recent_event(e, now) and upn.lower() in service.people(e)]
    result = []
    states = await service.recent_states(db, user, recent)
    for event in sorted(recent, key=lambda e: parse_graph_datetime(e["end"]), reverse=True):
        row = _format_event(event)
        row["status"] = "ended"
        row.update(states[service.occurrence_key(event)])
        result.append(row)
    return result


@router.post("/calendar/recent/process")
async def process_recent(body: EventReference, db: AsyncSession = Depends(get_db), upn: str = Depends(require_subscribed)):
    from ..services.cross_user_recordings import process_own_event
    return await process_own_event(db, upn, body.event_id)


def _event_status(start_str: str | None, end_str: str | None) -> str:
    """Compute whether a calendar event is currently in progress or still upcoming.

    Returns ``"in_progress"`` if ``now`` falls within [start, end], otherwise
    ``"upcoming"``.  Timestamps are parsed and normalised to UTC before comparison.
    Malformed timestamps fall back to ``"upcoming"`` rather than raising.
    """
    if not start_str:
        return "upcoming"
    now = datetime.now(timezone.utc)
    try:
        start = parse_graph_datetime(start_str)
        end_dt = parse_graph_datetime(end_str)
        if start is None:
            return "upcoming"
        if start <= now and (end_dt is None or now <= end_dt):
            return "in_progress"
    except Exception:
        pass
    return "upcoming"


def _format_event(e: dict) -> dict:
    """Reshape a raw Graph calendarView event dict into the API response shape.

    Adds the computed ``status`` field and flattens nested Graph objects
    (organizer, attendees, location) into a flat, frontend-friendly structure.
    """
    organizer = (e.get("organizer") or {}).get("emailAddress", {})
    attendees = [
        a["emailAddress"]["address"]
        for a in (e.get("attendees") or [])
        if a.get("emailAddress", {}).get("address")
    ]
    start = utc_iso(e.get("start"))
    end = utc_iso(e.get("end"))
    return {
        "event_id": e.get("id"),
        "subject": e.get("subject") or "Untitled Meeting",
        "start": start,
        "start_tz": "UTC",
        "source_timezone": (e.get("start") or {}).get("timeZone"),
        "original_timezone": e.get("originalStartTimeZone"),
        "end": end,
        "organizer_name": organizer.get("name"),
        "organizer_email": organizer.get("address"),
        "attendees": attendees,
        "attendee_count": len(attendees),
        "platform": e.get("onlineMeetingProvider", "teamsForBusiness"),
        "location": (e.get("location") or {}).get("displayName"),
        "status": _event_status(start, end),
    }


@router.get("/calendar/upcoming")
async def upcoming_meetings(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    upn: str = Depends(require_subscribed),
):
    """Return the user's upcoming online/Teams meetings for the next N days."""
    now = datetime.now(timezone.utc)
    events = list(await db.scalars(
        select(SyncedCalendarEvent.raw)
        .where(
            SyncedCalendarEvent.user_upn == upn,
            SyncedCalendarEvent.starts_at > now,
            SyncedCalendarEvent.starts_at <= now + timedelta(days=days),
        )
        .order_by(SyncedCalendarEvent.starts_at)
    ))
    # Background sync includes offline events for /calendar/recent; Upcoming
    # remains online-only and never performs a page-load Graph fallback.
    events = [e for e in events if e.get("isOnlineMeeting")]
    active = [e for e in events if not (e.get("subject") or "").lower().startswith("canceled:")]
    return [_format_event(e) for e in active]
