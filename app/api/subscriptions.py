"""Graph subscriptions expire after ~3 days for OneDrive resources.
POST /subscriptions/ensure creates or renews one subscription per opted-in user.
Call this endpoint on startup and on a daily cron job."""
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..graph.auth import get_token
from ..graph import client as graph
from ..models import RegisteredUser

settings = get_settings()
router = APIRouter()


async def _get_existing_subscriptions(client: httpx.AsyncClient) -> dict[str, dict]:
    """Return existing subscriptions keyed by their resource path."""
    r = await client.get(
        f"{settings.graph_base}/subscriptions",
        headers={"Authorization": f"Bearer {get_token()}"},
    )
    r.raise_for_status()
    return {s["resource"]: s for s in r.json().get("value", [])}


async def _upsert_subscription(
    client: httpx.AsyncClient,
    resource: str,
    existing: dict[str, dict],
) -> dict:
    expiry = (datetime.now(timezone.utc) + timedelta(days=2, hours=20)).isoformat()
    headers = {"Authorization": f"Bearer {get_token()}"}
    notification_url = f"{settings.webhook_base_url}/webhooks/graph"

    if resource in existing:
        sub_id = existing[resource]["id"]
        r = await client.patch(
            f"{settings.graph_base}/subscriptions/{sub_id}",
            headers=headers,
            json={"expirationDateTime": expiry},
        )
        r.raise_for_status()
        return {"action": "renewed", "resource": resource, "id": sub_id}

    payload = {
        "changeType": "updated",
        "notificationUrl": notification_url,
        "resource": resource,
        "expirationDateTime": expiry,
        "clientState": settings.webhook_client_state,
    }
    r = await client.post(
        f"{settings.graph_base}/subscriptions",
        headers=headers,
        json=payload,
    )
    r.raise_for_status()
    return {"action": "created", "resource": resource, "id": r.json()["id"]}


@router.post("/subscriptions/ensure")
async def ensure_subscriptions(
    x_subscription_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """Create or renew Graph webhooks for explicitly subscribed users only."""
    if not settings.subscription_secret or x_subscription_secret != settings.subscription_secret:
        raise HTTPException(status_code=401, detail="Invalid secret")

    users = (
        await db.scalars(
            select(RegisteredUser).where(RegisteredUser.is_subscribed.is_(True))
        )
    ).all()
    results = []

    async with httpx.AsyncClient(timeout=30) as client:
        existing = await _get_existing_subscriptions(client)

        for user in users:
            upn = user.upn
            try:
                drive_id = await graph.get_user_drive_id(upn)
                user.graph_drive_id = drive_id
                resource = f"/drives/{drive_id}/root"
                result = await _upsert_subscription(client, resource, existing)
                result["user"] = upn
                results.append(result)
            except Exception as e:
                results.append({"user": upn, "error": str(e)})
        await db.commit()

    return {"subscriptions": results, "total": len(results)}
