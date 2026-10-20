"""Durable, explicit calendar operations owned by the API lifespan, never the Worker.

No startup resume or automatic retries: a lost owner is an unknown outcome.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.models import CalendarSyncRun
from app.services.calendar_sync import _MANUAL_SYNC_LOCK, CalendarSyncBusy

log = logging.getLogger("meeting_intel.calendar_sync")
_tasks: dict[UUID, asyncio.Task] = {}
HEARTBEAT_SECONDS = 10
STALE_SECONDS = 60
RUN_SECONDS = 15 * 60
_stopping = False
_COUNTS = ("succeeded", "failed", "skipped", "created", "updated")


def now():
    return datetime.now(UTC)


def projection(row):
    heartbeat = row.heartbeat_at.replace(tzinfo=UTC) if row.heartbeat_at.tzinfo is None else row.heartbeat_at
    stale = row.status in {"queued", "running"} and heartbeat < now() - timedelta(seconds=STALE_SECONDS)
    return {
        "id": row.id, "status": "unknown" if stale else row.status,
        **{key: getattr(row, key) for key in _COUNTS},
        "error_category": "owner_unavailable" if stale else row.error_category,
        "retry_allowed": row.active_slot is None,
    }


async def get_run(run_id=None):
    async with SessionLocal() as db:
        if run_id is not None:
            row = await db.get(CalendarSyncRun, run_id)
        else:
            # An unresolved run always takes precedence over terminal history.
            row = await db.scalar(select(CalendarSyncRun).where(CalendarSyncRun.active_slot == 1))
            if row is None:
                row = await db.scalar(select(CalendarSyncRun).order_by(CalendarSyncRun.created_at.desc()).limit(1))
        return projection(row) if row is not None else None


@asynccontextmanager
async def exclusive_sync():
    # Transaction lock conflicts with the legacy session lock on the same key.
    # It is also released on rollback/disconnect with a transaction pooler.
    async with engine.connect() as conn, conn.begin():
        acquired = await conn.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _MANUAL_SYNC_LOCK})
        if not acquired:
            raise CalendarSyncBusy()
        yield


async def submit(run_id, requested_by):
    if _stopping:
        raise RuntimeError("API is shutting down")
    async with SessionLocal() as db:
        existing = await db.get(CalendarSyncRun, run_id)
        if existing is not None:
            return projection(existing)  # Never restart an idempotent request.
        active = await db.scalar(select(CalendarSyncRun).where(CalendarSyncRun.active_slot == 1))
        if active is not None:
            return projection(active)
        # Also respect a legacy synchronous operation that has no run row.
        async with exclusive_sync():
            row = CalendarSyncRun(id=run_id, requested_by=requested_by)
            db.add(row)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                active = await db.get(CalendarSyncRun, run_id)
                if active is None:
                    active = await db.scalar(select(CalendarSyncRun).where(CalendarSyncRun.active_slot == 1))
                if active is None:
                    raise
                return projection(active)
        # A crash after commit (including during lock cleanup) leaves a durable
        # queued row that becomes unknown; another request must not restart it.
        task = asyncio.create_task(execute(run_id), name=f"calendar-sync-{run_id}")
        _tasks[run_id] = task
        task.add_done_callback(lambda completed: _tasks.pop(run_id, None))
        log.info("calendar_sync accepted run_id=%s", run_id)
        return projection(row)


async def progress(db, run_id, **counts):
    """Called in the SAME transaction as each user's calendar and sync-state writes."""
    row = await db.get(CalendarSyncRun, run_id, with_for_update=True)
    if row is None or row.status != "running":
        raise RuntimeError("Calendar run is not running")
    for key, amount in counts.items():
        if key not in _COUNTS:
            raise ValueError("Invalid counter")
        setattr(row, key, getattr(row, key) + amount)
    row.heartbeat_at = now()
    await db.commit()
    log.info("calendar_sync progress run_id=%s counts=%s", run_id, counts)


async def finish(run_id, status, error_category=None):
    async with SessionLocal() as db:
        row = await db.get(CalendarSyncRun, run_id, with_for_update=True)
        if row.status in {"success", "partial", "failed"}:
            return  # A cleanup failure cannot erase an already durable result.
        row.status = status
        row.error_category = error_category
        row.finished_at = now()
        row.heartbeat_at = now()
        # Unknown retains the singleton slot; no automatic retry after partial work.
        row.active_slot = 1 if status == "unknown" else None
        await db.commit()
        log.info("calendar_sync terminal run_id=%s status=%s counts=%s category=%s", run_id,
                 status, {key: getattr(row, key) for key in _COUNTS}, error_category)


async def heartbeat(run_id):
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        async with SessionLocal() as db:
            row = await db.get(CalendarSyncRun, run_id, with_for_update=True)
            if row.status != "running":
                return
            row.heartbeat_at = now()
            await db.commit()


async def execute(run_id):
    from app.services.calendar_sync import _sync_subscribers

    pulse = None
    try:
        async with asyncio.timeout(RUN_SECONDS), exclusive_sync():
            async with SessionLocal() as db:
                row = await db.get(CalendarSyncRun, run_id, with_for_update=True)
                row.status = "running"
                row.heartbeat_at = now()
                await db.commit()
            log.info("calendar_sync running run_id=%s", run_id)
            pulse = asyncio.create_task(heartbeat(run_id))
            sync = asyncio.create_task(_sync_subscribers(run_id=run_id))
            try:
                done, _ = await asyncio.wait({pulse, sync}, return_when=asyncio.FIRST_COMPLETED)
                if pulse in done and sync not in done:
                    # A failed heartbeat must stop new work, not leave an orphan.
                    await pulse
                    raise RuntimeError("Calendar heartbeat stopped")
                result = await sync
                await finish(run_id, result["status"])
            finally:
                sync.cancel()
                await asyncio.gather(sync, return_exceptions=True)
    except asyncio.CancelledError:
        await mark_unknown(run_id, "interrupted")
        raise
    except TimeoutError:
        await mark_unknown(run_id, "operation_deadline")
    except CalendarSyncBusy:
        await mark_unknown(run_id, "legacy_sync_running")
    except Exception:  # noqa: BLE001 -- operation boundary stores only safe categories.
        await mark_unknown(run_id, "infrastructure_unconfirmed")
    finally:
        if pulse is not None:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)


async def mark_unknown(run_id, category):
    try:
        async with asyncio.timeout(5):
            await finish(run_id, "unknown", category)
    except Exception:  # noqa: BLE001 -- DB failure must leave a stale, blocked run.
        # Persisted heartbeat will expire. Never emit exception bodies or release
        # the active slot merely because the database is unavailable.
        log.error("calendar_sync status_unconfirmed run_id=%s category=%s", run_id, category)


async def shutdown():
    global _stopping
    _stopping = True
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def start_lifespan():
    global _stopping
    _stopping = False
