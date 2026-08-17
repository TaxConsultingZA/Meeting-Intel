"""Persist Microsoft Graph sync outcomes for honest UI and operational diagnosis."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserSyncState


def _clean_error(error: object) -> str:
    # Graph/httpx exceptions can contain long URLs and response bodies.  Keep a
    # bounded diagnostic message and never persist access tokens or headers.
    text = str(error).replace("\r", " ").replace("\n", " ").strip()
    return text[:1000] or "Unknown Microsoft Graph error"


async def record_sync_result(
    db: AsyncSession,
    *,
    user_upn: str,
    source: str,
    error: object | None = None,
) -> UserSyncState:
    upn = user_upn.strip().lower()
    now = datetime.now(timezone.utc)
    row = await db.scalar(
        select(UserSyncState).where(
            UserSyncState.user_upn == upn,
            UserSyncState.source == source,
        )
    )
    if row is None:
        row = UserSyncState(user_upn=upn, source=source)
        db.add(row)
    row.last_attempted_at = now
    if error is None:
        row.status = "success"
        row.last_succeeded_at = now
        row.last_error = None
    else:
        row.status = "failed"
        row.last_error = _clean_error(error)
    await db.commit()
    return row
