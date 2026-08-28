"""Persist Outlook calendar data for users who explicitly opted in."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.graph import client as graph
from app.models import RegisteredUser, SyncedCalendarEvent
from app.services.sync_state import record_sync_result
from app.utils.timezones import parse_graph_datetime


def _graph_datetime(value: dict | None) -> datetime | None:
    return parse_graph_datetime(value)


async def sync_calendar_events(days: int = 14) -> int:
    """Fetch and upsert calendar events for subscribed users only."""
    async with SessionLocal() as db:
        upns = (
            await db.scalars(
                select(RegisteredUser.upn).where(RegisteredUser.is_subscribed.is_(True))
            )
        ).all()

    synced = 0
    for upn in upns:
        try:
            events = await graph.get_upcoming_calendar_events(upn, days=days)
        except Exception as exc:
            # One user's Graph failure must not block every other subscriber.
            async with SessionLocal() as db:
                await record_sync_result(db, user_upn=upn, source="calendar", error=exc)
            continue
        async with SessionLocal() as db:
            for raw in events:
                event_id = raw.get("id")
                if not event_id:
                    continue
                row = await db.scalar(
                    select(SyncedCalendarEvent).where(
                        SyncedCalendarEvent.user_upn == upn,
                        SyncedCalendarEvent.event_id == event_id,
                    )
                )
                if row is None:
                    row = SyncedCalendarEvent(user_upn=upn, event_id=event_id, raw=raw)
                    db.add(row)
                row.subject = raw.get("subject")
                row.starts_at = _graph_datetime(raw.get("start"))
                row.ends_at = _graph_datetime(raw.get("end"))
                row.raw = raw
                row.last_synced_at = datetime.now(timezone.utc)
                synced += 1
            await db.commit()
            await record_sync_result(db, user_upn=upn, source="calendar")
    return synced
