"""Explicit calendar-only sync; no queue, recording discovery or scheduler calls."""
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.graph import client as graph
from app.models import RegisteredUser
from app.services.sync_state import record_sync_result
from app.workers.sync_microsoft import store_calendar_events


_MANUAL_SYNC_LOCK = 0x4D4943414C


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


async def _sync_subscribers() -> dict:
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
                continue
            upn = user.upn
            try:
                events = await graph.get_upcoming_calendar_events(
                    upn, days=14, include_offline=True,
                )
                created, updated = await store_calendar_events(db, upn, events)
            except Exception:
                await db.rollback()
                # Do not persist vendor bodies, URLs, tokens or calendar content.
                await record_sync_result(
                    db, user_upn=upn, source="calendar",
                    error="Calendar sync failed. Check existing Microsoft access or retry manually.",
                )
                counts["failed"] += 1
                continue
            counts["created"] += created
            counts["updated"] += updated
            counts["succeeded"] += 1
            await record_sync_result(db, user_upn=upn, source="calendar")

    return {"status": "partial" if counts["failed"] and counts["succeeded"] else
            "failed" if counts["failed"] else "success", **counts}
