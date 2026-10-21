import asyncio
import logging
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import RegisteredUser, SyncedCalendarEvent
from ..services import calendar_runs
from ..services.calendar_sync import CalendarSyncBusy
from ..utils.timezones import parse_graph_datetime, utc_iso
from .deps import registered_user, require_subscribed
from .recording_processing_requests import EventReference

log = logging.getLogger("meeting_intel.calendar_sync")


class CalendarSyncRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def observed(request):
            if not request.url.path.startswith("/calendar/sync"):
                return await handler(request)
            started = monotonic()
            diagnostic_id = uuid4()
            edge_id = request.headers.get("x-railway-request-id", "unavailable")
            if len(edge_id) > 128 or any(not (char.isalnum() or char in "-_") for char in edge_id):
                edge_id = "unavailable"
            request.state.sync_phase = "authentication"
            request.state.sync_run_id = None
            status = 500
            log.info("calendar_sync request_started diagnostic_id=%s edge_request_id=%s method=%s",
                     diagnostic_id, edge_id, request.method)
            try:
                async with asyncio.timeout(20):
                    response = await handler(request)
                    status = response.status_code
                    return response
            except TimeoutError:
                status = 503
                log.warning("calendar_sync request_timeout diagnostic_id=%s phase=%s", diagnostic_id, request.state.sync_phase)
                raise HTTPException(503, "Calendar sync status is unconfirmed. Check status; do not resubmit.") from None
            except HTTPException as exc:
                status = exc.status_code
                raise
            finally:
                log.info("calendar_sync request_finished diagnostic_id=%s run_id=%s phase=%s status=%d elapsed_ms=%d",
                         diagnostic_id, request.state.sync_run_id, request.state.sync_phase, status,
                         int((monotonic() - started) * 1000))
        return observed


router = APIRouter(route_class=CalendarSyncRoute)


class CalendarSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class CalendarSyncResult(BaseModel):
    id: UUID
    status: Literal["queued", "running", "success", "partial", "failed", "unknown"]
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    created: int = Field(ge=0)
    updated: int = Field(ge=0)
    error_category: str | None
    retry_allowed: bool


@router.post("/calendar/sync", response_model=CalendarSyncResult, status_code=202)
async def sync_calendar_now(body: CalendarSyncRequest, request: Request,
                            user: Annotated[RegisteredUser, Depends(registered_user)]):
    if not user.is_admin or not user.is_subscribed:
        raise HTTPException(403, "A subscribed administrator is required for calendar sync")
    try:
        request.state.sync_phase = "acceptance"
        request.state.sync_run_id = body.request_id
        result = await calendar_runs.submit(body.request_id, user.id)
        request.state.sync_run_id = result["id"]
        return result
    except CalendarSyncBusy:
        raise HTTPException(409, "Calendar sync is already running. Wait before trying again.") from None
    except Exception:  # noqa: BLE001 -- operation boundary must not expose database errors.
        raise HTTPException(503, "Calendar sync could not be completed. Check sync status before trying again.") from None


@router.get("/calendar/sync", response_model=CalendarSyncResult | None)
async def calendar_sync_status(request: Request,
                               user: Annotated[RegisteredUser, Depends(registered_user)],
                               run_id: UUID | None = None):
    if not user.is_admin or not user.is_subscribed:
        raise HTTPException(403, "A subscribed administrator is required for calendar sync")
    request.state.sync_phase = "status"
    try:
        result = await calendar_runs.get_run(run_id)
    except Exception:  # noqa: BLE001 -- operation boundary must not expose database errors.
        raise HTTPException(503, "Calendar sync status is unavailable; do not resubmit.") from None
    if run_id is not None and result is None:
        raise HTTPException(404, "Calendar sync acceptance is unconfirmed; do not resubmit.")
    return result


@router.get("/calendar/recent")
async def recent_meetings(db: AsyncSession = Depends(get_db), upn: str = Depends(require_subscribed),
                          all_available: bool = False):
    """Read cached events only; the catalog opts out of the recent-time window."""
    from ..services import cross_user_recordings as service
    now = datetime.now(timezone.utc)
    query = select(SyncedCalendarEvent.raw).where(SyncedCalendarEvent.user_upn == upn)
    if not all_available:
        query = query.where(
            SyncedCalendarEvent.ends_at >= now - timedelta(days=30),
            SyncedCalendarEvent.ends_at < now,
        )
    events = list(await db.scalars(query))
    user = await service.user_by_upn(db, upn)
    recent = [e for e in events if upn.lower() in service.people(e)
              and (all_available or service.recent_event(e, now))]
    result = []
    states = (await service.recent_states(db, user, recent, all_available=True) if all_available
              else await service.recent_states(db, user, recent))
    for event in sorted(recent, key=lambda e: parse_graph_datetime(e.get("end"))
                        or datetime.min.replace(tzinfo=now.tzinfo), reverse=True):
        row = _format_event(event)
        end = parse_graph_datetime(event.get("end"))
        if not all_available or (end and end <= now):
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
