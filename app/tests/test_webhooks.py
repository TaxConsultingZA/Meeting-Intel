"""Webhook notifications must remain behind the user's current opt-in state."""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(db):
    from app.api.webhooks import router
    from app.db import get_db

    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _notification(client_state):
    return {
        "value": [
            {
                "clientState": client_state,
                "resource": "/drives/drive-123/items/item-456",
                "resourceData": {"id": "item-456", "eTag": "etag"},
            }
        ]
    }


def test_stale_webhook_for_unsubscribed_drive_is_ignored():
    from app.api import webhooks

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    with patch("app.api.webhooks.enqueue_recording_job", new_callable=AsyncMock) as enqueue:
        response = _client(db).post(
            "/webhooks/graph",
            json=_notification(webhooks.settings.webhook_client_state),
        )
    assert response.status_code == 202
    enqueue.assert_not_awaited()


def test_subscribed_drive_notification_can_be_claimed_and_queued():
    from app.api import webhooks

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock(is_subscribed=True))
    with patch(
        "app.api.webhooks.enqueue_recording_job",
        new_callable=AsyncMock,
        return_value=True,
    ) as enqueue:
        response = _client(db).post(
            "/webhooks/graph",
            json=_notification(webhooks.settings.webhook_client_state),
        )
    assert response.status_code == 202
    enqueue.assert_awaited_once_with(
        db,
        drive_item_id="item-456",
        drive_id="drive-123",
        owner_upn=db.scalar.return_value.upn,
        source="webhook",
        etag="etag",
    )
