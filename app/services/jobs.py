from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RecordingJob
from .ledger import claim_item
from .audit import add_audit_event


ACTIVE_JOB_STATUSES = ("pending", "processing")
UNRESOLVED_PROVIDER_STATUSES = (
    "submitting", "submission_unknown", "submitted", "queued", "processing", "poll_unknown",
)


async def enqueue_recording_job(
    db: AsyncSession,
    *,
    drive_item_id: str,
    drive_id: str,
    owner_upn: str,
    source: str,
    etag: str | None = None,
    filename: str | None = None,
    commit: bool = True,
    job_id: UUID | None = None,
    authorized_by: str | None = None,
) -> bool:
    """Atomically claim a new Graph item and persist its processing job."""
    claimed = await claim_item(
        db, drive_item_id, drive_id, etag, source, filename=filename, commit=False
    )
    if not claimed:
        return False
    created_id = job_id or uuid4()
    db.add(RecordingJob(
        id=created_id,
        drive_item_id=drive_item_id,
        drive_id=drive_id,
        owner_upn=owner_upn,
        source=source,
        **admission(authorized_by),
    ))
    _audit_created(db, created_id, source)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True


async def enqueue_retry_job(
    db: AsyncSession,
    *,
    drive_item_id: str,
    drive_id: str,
    owner_upn: str,
    source: str = "manual_retry",
    commit: bool = True,
    job_id: UUID | None = None,
    authorized_by: str | None = None,
) -> bool:
    """Persist a retry unless this item already has active queued work."""
    active = await db.scalar(
        select(RecordingJob.id).where(
            RecordingJob.drive_item_id == drive_item_id,
            (RecordingJob.status.in_(ACTIVE_JOB_STATUSES)
             | RecordingJob.provider_status.in_(UNRESOLVED_PROVIDER_STATUSES)),
        )
    )
    if active:
        return False
    statement = insert(RecordingJob).values(
        **({"id": job_id} if job_id is not None else {}),
        drive_item_id=drive_item_id,
        drive_id=drive_id,
        owner_upn=owner_upn,
        source=source,
        **admission(authorized_by),
        available_at=datetime.now(timezone.utc),
    ).on_conflict_do_nothing(
        index_elements=[RecordingJob.drive_item_id],
        index_where=RecordingJob.status.in_(ACTIVE_JOB_STATUSES),
    ).returning(RecordingJob.id)
    created_id = await db.scalar(statement)
    if created_id is None:
        await db.rollback()
        return False
    _audit_created(db, created_id, source)
    if commit:
        await db.commit()
    return created_id is not None


def admission(actor: str | None) -> dict:
    """Source/manual strings grant nothing without explicit caller authorization."""
    return (dict(admission_version=1, authorized_at=datetime.now(timezone.utc),
                 authorized_by=actor) if actor else {})


def _audit_created(db, job_id, source):
    add_audit_event(db, event_type="recording.created", outcome="succeeded",
        actor_type="system", actor_id="recording_queue",
        resource_type="recording_job", resource_id=job_id, job_id=job_id,
        correlation_id=job_id, event_key=f"recording.created:{job_id}",
        metadata={"source": source, "new_state": "pending"})
