"""Explicit calendar-only sync; no queue, recording discovery or scheduler calls."""
import asyncio
import logging

from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.graph import client as graph
from app.models import RegisteredUser
from app.services.sync_state import record_sync_result
from app.workers.sync_microsoft import store_calendar_events

_MANUAL_SYNC_LOCK = 0x4D4943414C
log = logging.getLogger("meeting_intel.calendar_sync")


class CalendarSyncBusy(Exception):
    pass


async def sync_subscribed_calendars_once() -> dict:
    """One run, serialized across API instances using a session advisory lock.

    An Entra identity link is not a Graph grant. Reads use the existing app-only
    authorization; Microsoft rejects missing/revoked calendar access. No consent,
    delegated tokens, permission changes or retry are introduced here.
    """
    async with engine.connect() as connection:
        acquired = None
        try:
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": _MANUAL_SYNC_LOCK},
            )
            await connection.commit()
            if not acquired:
                raise CalendarSyncBusy()
            return await _sync_subscribers()
        finally:
            if acquired is None:
                await connection.invalidate()  # Acquisition may have succeeded before cancellation.
            elif acquired:
                try:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": _MANUAL_SYNC_LOCK},
                    )
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()  # Never return a locked session to the pool.
                    raise


async def _sync_subscribers(run_id=None) -> dict:
    from app.services.calendar_runs import progress

    log.info("calendar_sync stage run_id=%s stage=subscriber_snapshot", run_id)
    async with SessionLocal() as db:
        user_ids = (await db.scalars(select(RegisteredUser.id).where(
            RegisteredUser.is_subscribed.is_(True),
        ))).all()

    counts = dict(succeeded=0, failed=0, skipped=0, created=0, updated=0)
    for user_id in user_ids:
        async with SessionLocal() as db:
            # Recheck and lock each subscription before Graph access. Unsubscribe
            # uses the same row lock, so an opt-out cannot race this read.
            user = await db.scalar(select(RegisteredUser).where(
                RegisteredUser.id == user_id,
                RegisteredUser.is_subscribed.is_(True),
                RegisteredUser.entra_oid.is_not(None),
                RegisteredUser.entra_oid != "",
            ).with_for_update())
            if user is None:
                counts["skipped"] += 1
                if run_id is not None:
                    await progress(db, run_id, skipped=1)
                continue
            upn = user.upn
            try:
                log.info("calendar_sync stage run_id=%s stage=microsoft_read", run_id)
                async with asyncio.timeout(90):
                    events = await graph.get_upcoming_calendar_events(
                        upn, days=14, include_offline=True,
                    )
            except Exception:
                await db.rollback()
                # Do not persist vendor bodies, URLs, tokens or calendar content.
                await record_sync_result(
                    db, user_upn=upn, source="calendar",
                    error="Calendar sync failed. Check existing Microsoft access or retry manually.",
                    commit=run_id is None,
                )
                counts["failed"] += 1
                if run_id is not None:
                    await progress(db, run_id, failed=1)
                continue
            # Write/commit failures are ambiguous infrastructure outcomes, not
            # Microsoft permission failures. Stop instead of continuing/retrying.
            log.info("calendar_sync stage run_id=%s stage=calendar_write", run_id)
            if run_id is None:
                created, updated = await store_calendar_events(db, upn, events)
            else:
                created, updated = await store_calendar_events(db, upn, events, commit=False)
            counts["created"] += created
            counts["updated"] += updated
            counts["succeeded"] += 1
            await record_sync_result(db, user_upn=upn, source="calendar", commit=run_id is None)
            if run_id is not None:
                await progress(db, run_id, succeeded=1, created=created, updated=updated)

    return {"status": "partial" if counts["failed"] and counts["succeeded"] else
            "failed" if counts["failed"] else "success", **counts}
