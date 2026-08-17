from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import ProcessedItem


async def claim_item(
    db: AsyncSession,
    drive_item_id: str,
    drive_id: str | None,
    etag: str | None,
    source: str,
    *,
    commit: bool = True,
) -> bool:
    """Returns True if this is the first time we've seen the item (claim succeeds),
    False if already processed. Handles duplicate webhooks AND reconcile re-finds."""
    existing = await db.scalar(
        select(ProcessedItem).where(ProcessedItem.drive_item_id == drive_item_id)
    )
    if existing:
        return False
    db.add(ProcessedItem(drive_item_id=drive_item_id, drive_id=drive_id, etag=etag, source=source))
    try:
        if commit:
            await db.commit()
        else:
            await db.flush()
    except IntegrityError:
        # Two webhook/reconcile requests may race between SELECT and INSERT.
        # The unique constraint is the final authority; treat the loser as an
        # already-claimed item instead of returning a 500 response.
        await db.rollback()
        return False
    return True
