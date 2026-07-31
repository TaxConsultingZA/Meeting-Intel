from fastapi import APIRouter, Request, Response, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..services.ledger import claim_item
from ..queue.bus import enqueue_job
from ..models import RegisteredUser

settings = get_settings()
router = APIRouter()


def _parse_drive_id(resource_path: str) -> str | None:
    # Graph resource paths look like: /drives/{driveId}/items/{itemId}
    parts = resource_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "drives":
        return parts[1]
    return None


@router.post("/webhooks/graph")
async def graph_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # 1) Subscription validation handshake
    token = request.query_params.get("validationToken")
    if token:
        return Response(content=token, media_type="text/plain")

    body = await request.json()
    for note in body.get("value", []):
        if note.get("clientState") != settings.webhook_client_state:
            continue

        resource = note.get("resourceData", {}) or {}
        drive_item_id = resource.get("id")
        etag = resource.get("eTag")
        if not drive_item_id:
            continue

        # Drive ID is encoded in the resource path — tells us whose OneDrive this is
        drive_id = _parse_drive_id(note.get("resource", ""))
        if not drive_id:
            continue

        # A valid Graph notification is not consent by itself. Ignore stale or
        # unexpected subscriptions unless this drive still belongs to an opted-in user.
        subscriber = await db.scalar(
            select(RegisteredUser).where(
                RegisteredUser.graph_drive_id == drive_id,
                RegisteredUser.is_subscribed.is_(True),
            )
        )
        if not subscriber:
            continue

        if await claim_item(db, drive_item_id, drive_id, etag, source="webhook"):
            enqueue_job(drive_item_id, drive_id)

    # Always 202 fast — Graph times out if you process inline
    return Response(status_code=202)
