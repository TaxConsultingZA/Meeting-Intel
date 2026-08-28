"""Durable PostgreSQL worker: python -m app.queue.worker.

Row locks arbitrate claims; fenced leases allow crash recovery. A session
advisory lock protects live pipelines during delayed heartbeats. Requires a
direct/session-pooled PostgreSQL connection, not transaction pooling.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import signal
import uuid

from sqlalchemy import or_, select, text, update

from ..config import get_settings
from ..db import SessionLocal, engine
from ..models import Meeting, ProcessingState, RecordingJob
from ..pipeline.steps import process_recording

settings = get_settings()
logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def _lock_key(drive_item_id: str) -> int:
    # Stable across processes; retain the project's existing recording identity.
    return int.from_bytes(hashlib.sha256(drive_item_id.encode()).digest()[:8],
                          "big", signed=True)


def _retry_or_fail(job, error: Exception) -> None:
    job.locked_at = None
    job.lease_token = None
    job.last_error = str(error)[:4000]
    if job.attempts < job.max_attempts:
        job.status = "pending"
        job.available_at = _now() + timedelta(
            seconds=min(300, 15 * 2 ** min(5, max(0, job.attempts - 1)))
        )
    else:
        job.status = "failed"


async def _mark_meeting_interrupted(db, job):
    # Crash recovery must not leave the review UI permanently "transcribing".
    # Never overwrite a meeting whose final review commit already succeeded.
    await db.execute(update(Meeting).where(
        Meeting.drive_item_id == job.drive_item_id,
        Meeting.state.in_((ProcessingState.queued, ProcessingState.downloading,
                          ProcessingState.transcribing, ProcessingState.extracting,
                          ProcessingState.failed)),
    ).values(state=ProcessingState.failed, error=job.last_error[:2000]))


async def _recover_interrupted_jobs() -> None:
    """Recover only expired leases, never all jobs owned by other workers."""
    async with SessionLocal() as db:
        jobs = await db.scalars(
            select(RecordingJob).where(
                RecordingJob.status == "processing",
                or_(RecordingJob.locked_at.is_(None),
                    RecordingJob.locked_at < _now() - timedelta(seconds=settings.worker_lease_seconds)),
            ).order_by(RecordingJob.locked_at).with_for_update(skip_locked=True).limit(100)
        )
        for job in jobs:
            # A slow heartbeat must not reclaim a pipeline still holding its lock.
            if await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"),
                               {"key": _lock_key(job.drive_item_id)}):
                _retry_or_fail(job, RuntimeError("Worker lease expired; interrupted attempt"))
                await _mark_meeting_interrupted(db, job)
        await db.commit()


async def _claim_next() -> RecordingJob | None:
    async with SessionLocal() as db:
        await db.execute(update(RecordingJob).where(
            RecordingJob.status == "pending",
            RecordingJob.attempts >= RecordingJob.max_attempts,
        ).values(status="failed", last_error="Maximum attempts exhausted"))
        job = await db.scalar(
            select(RecordingJob).where(
                RecordingJob.status == "pending",
                RecordingJob.attempts < RecordingJob.max_attempts,
                RecordingJob.available_at <= _now(),
            ).order_by(RecordingJob.created_at).with_for_update(skip_locked=True).limit(1)
        )
        if job is not None:
            job.status = "processing"
            job.attempts += 1
            job.locked_at = _now()
            job.lease_token = uuid.uuid4()
            job.last_error = None
        await db.commit()
        if job is not None:
            db.expunge(job)
        return job


def _owned(job_id, lease_token):
    return (RecordingJob.id == job_id, RecordingJob.status == "processing",
            RecordingJob.lease_token == lease_token)


async def _renew(job_id, lease_token) -> bool:
    async with SessionLocal() as db:
        renewed = await db.scalar(update(RecordingJob).where(*_owned(job_id, lease_token))
                                  .values(locked_at=_now()).returning(RecordingJob.id))
        await db.commit()
        return renewed is not None


async def _finish(job_id, lease_token, error: Exception | None = None) -> None:
    async with SessionLocal() as db:
        job = await db.scalar(select(RecordingJob).where(*_owned(job_id, lease_token))
                              .with_for_update())
        if job is None:
            return  # Superseded workers must not finish another worker's lease.
        if error is None:
            job.status = "completed"
            job.last_error = None
            job.locked_at = None
            job.lease_token = None
        else:
            _retry_or_fail(job, error)
            await _mark_meeting_interrupted(db, job)
        await db.commit()


@asynccontextmanager
async def _recording_lock(drive_item_id):
    async with engine.connect() as conn:
        key = _lock_key(drive_item_id)
        acquired = None
        try:
            acquired = await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            await conn.commit()  # Session lock survives; no idle transaction.
            if not acquired:
                raise RuntimeError("Recording is still owned by another worker")
            yield
        finally:
            if acquired is None:
                # Cancellation/connection loss during acquisition leaves lock
                # ownership uncertain: do not reuse that pooled connection.
                await conn.invalidate()
            elif acquired:
                try:
                    await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    await conn.commit()
                except BaseException:
                    await conn.invalidate()  # Never return a locked session to the pool.
                    raise


async def _heartbeat(job_id, token):
    while True:
        await asyncio.sleep(settings.worker_heartbeat_seconds)
        if not await _renew(job_id, token):
            raise RuntimeError("Worker lost its recording lease")


async def _process(job):
    async with SessionLocal() as db:
        await process_recording(db, job.drive_item_id, job.drive_id, owner_upn=job.owner_upn)


async def _execute(job):
    token = job.lease_token
    try:
        async with _recording_lock(job.drive_item_id):
            if not await _renew(job.id, token):
                raise RuntimeError("Recording lease was superseded before processing")
            work = asyncio.create_task(_process(job))
            heartbeat = asyncio.create_task(_heartbeat(job.id, token))
            try:
                done, _ = await asyncio.wait((work, heartbeat), return_when=asyncio.FIRST_COMPLETED)
                if heartbeat in done:
                    await heartbeat
                await work
            finally:
                for task in (work, heartbeat):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(work, heartbeat, return_exceptions=True)
            await _finish(job.id, token)
    except asyncio.CancelledError:
        await _finish(job.id, token, RuntimeError("Worker stopped during processing"))
        raise
    except Exception as exc:
        logger.warning("Recording job %s failed (%s)", job.id, type(exc).__name__)
        await _finish(job.id, token, exc)


def _install_stop_handlers(stop):
    loop = asyncio.get_running_loop()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    def restore():
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return restore


async def _idle(stop):
    try:
        await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
    except asyncio.TimeoutError:
        pass


async def run_worker(stop_event: asyncio.Event | None = None) -> None:
    if settings.worker_heartbeat_seconds >= settings.worker_lease_seconds:
        raise ValueError("WORKER_HEARTBEAT_SECONDS must be less than WORKER_LEASE_SECONDS")
    stop = stop_event if stop_event is not None else asyncio.Event()
    restore = _install_stop_handlers(stop) if stop_event is None else lambda: None
    try:
        while not stop.is_set():
            try:
                await _recover_interrupted_jobs()
                if stop.is_set():
                    break
                job = await _claim_next()
                if job is None:
                    await _idle(stop)
                    continue
                if stop.is_set():
                    await _finish(job.id, job.lease_token, RuntimeError("Worker stopping"))
                    break
                task = asyncio.create_task(_execute(job))
                stopping = asyncio.create_task(stop.wait())
                try:
                    done, _ = await asyncio.wait((task, stopping), return_when=asyncio.FIRST_COMPLETED)
                    if stopping in done:
                        try:
                            await asyncio.wait_for(asyncio.shield(task), settings.worker_shutdown_seconds)
                        except asyncio.TimeoutError:
                            task.cancel()
                    await task
                except asyncio.CancelledError:
                    if not stop.is_set():
                        raise
                finally:
                    for child in (task, stopping):
                        if not child.done():
                            child.cancel()
                    await asyncio.gather(task, stopping, return_exceptions=True)
            except Exception:
                logger.exception("Worker queue operation failed; retrying after idle interval")
                await _idle(stop)
    finally:
        restore()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
