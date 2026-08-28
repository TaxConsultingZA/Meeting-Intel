from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..graph import client as graph
from ..services.sync_state import record_sync_result
from .deps import require_subscribed
from ..utils.timezones import parse_graph_datetime, utc_iso

router = APIRouter()


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
    try:
        events = await graph.get_upcoming_calendar_events(upn, days=days)
    except Exception as e:
        await record_sync_result(db, user_upn=upn, source="calendar", error=e)
        raise HTTPException(status_code=502, detail=f"Could not reach calendar: {e}")
    await record_sync_result(db, user_upn=upn, source="calendar")
    active = [e for e in events if not (e.get("subject") or "").lower().startswith("canceled:")]
    return [_format_event(e) for e in active]
