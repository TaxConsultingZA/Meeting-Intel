from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RecordingJob
from .ledger import claim_item


ACTIVE_JOB_STATUSES = ("pending", "processing")


async def enqueue_recording_job(
    db: AsyncSession,
    *,
    drive_item_id: str,
    drive_id: str,
    owner_upn: str,
    source: str,
    etag: str | None = None,
) -> bool:
    """Atomically claim a new Graph item and persist its processing job."""
    claimed = await claim_item(
        db, drive_item_id, drive_id, etag, source, commit=False
    )
    if not claimed:
        return False
    db.add(RecordingJob(
        drive_item_id=drive_item_id,
        drive_id=drive_id,
        owner_upn=owner_upn,
        source=source,
    ))
    await db.commit()
    return True


async def enqueue_retry_job(
    db: AsyncSession,
    *,
    drive_item_id: str,
    drive_id: str,
    owner_upn: str,
) -> bool:
    """Persist a retry unless this item already has active queued work."""
    active = await db.scalar(
        select(RecordingJob.id).where(
            RecordingJob.drive_item_id == drive_item_id,
            RecordingJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if active:
        return False
    statement = insert(RecordingJob).values(
        drive_item_id=drive_item_id,
        drive_id=drive_id,
        owner_upn=owner_upn,
        source="manual_retry",
        available_at=datetime.now(timezone.utc),
    ).on_conflict_do_nothing(
        index_elements=[RecordingJob.drive_item_id],
        index_where=RecordingJob.status.in_(ACTIVE_JOB_STATUSES),
    ).returning(RecordingJob.id)
    created_id = await db.scalar(statement)
    await db.commit()
    return created_id is not None
