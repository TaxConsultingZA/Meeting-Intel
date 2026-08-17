"""Durable PostgreSQL-backed recording worker.

Run this as a separate Railway worker service with:
``python -m app.queue.worker``.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from ..db import SessionLocal
from ..models import RecordingJob
from ..pipeline.steps import process_recording


POLL_SECONDS = 3


async def _recover_interrupted_jobs() -> None:
    """Return jobs left processing by a previous worker process to the queue."""
    async with SessionLocal() as db:
        await db.execute(
            update(RecordingJob)
            .where(RecordingJob.status == "processing")
            .values(
                status="pending",
                locked_at=None,
                available_at=datetime.now(timezone.utc),
                last_error="Worker restarted while this job was processing",
            )
        )
        await db.commit()


async def _claim_next() -> RecordingJob | None:
    async with SessionLocal() as db:
        job = await db.scalar(
            select(RecordingJob)
            .where(
                RecordingJob.status == "pending",
                RecordingJob.available_at <= datetime.now(timezone.utc),
            )
            .order_by(RecordingJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        job.status = "processing"
        job.attempts += 1
        job.locked_at = datetime.now(timezone.utc)
        job.last_error = None
        await db.commit()
        await db.refresh(job)
        db.expunge(job)
        return job


async def _finish(job_id, error: Exception | None = None) -> None:
    async with SessionLocal() as db:
        job = await db.get(RecordingJob, job_id)
        if not job:
            return
        job.locked_at = None
        if error is None:
            job.status = "completed"
            job.last_error = None
        elif job.attempts < job.max_attempts:
            job.status = "pending"
            job.last_error = str(error)[:4000]
            job.available_at = datetime.now(timezone.utc) + timedelta(
                seconds=min(300, 15 * (2 ** (job.attempts - 1)))
            )
        else:
            job.status = "failed"
            job.last_error = str(error)[:4000]
        await db.commit()


async def run_worker() -> None:
    await _recover_interrupted_jobs()
    print("Recording worker listening on the PostgreSQL job queue...")
    while True:
        job = await _claim_next()
        if job is None:
            await asyncio.sleep(POLL_SECONDS)
            continue
        try:
            async with SessionLocal() as db:
                await process_recording(
                    db,
                    job.drive_item_id,
                    job.drive_id,
                    owner_upn=job.owner_upn,
                )
        except Exception as exc:
            print(f"Job {job.id} failed on attempt {job.attempts}: {exc}")
            await _finish(job.id, exc)
        else:
            await _finish(job.id)
            print(f"Job {job.id} completed")


if __name__ == "__main__":
    asyncio.run(run_worker())
