from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(caller, target=1, states=()):
    from app.api.admin import router
    from app.db import get_db

    app = FastAPI()
    app.include_router(router)

    async def override_db():
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[caller, target])
        result = MagicMock()
        result.all.return_value = list(states)
        db.scalars = AsyncMock(return_value=result)
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app, raise_server_exceptions=False)


def _user(is_admin):
    user = MagicMock()
    user.is_admin = is_admin
    return user


def test_admin_can_retrieve_safe_sync_diagnostics_for_another_user():
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    state = MagicMock(
        source="calendar", status="failed", last_attempted_at=now,
        last_succeeded_at=None, last_error="Graph request failed",
        access_token="secret-token", refresh_token="secret-refresh",
    )
    response = _client(_user(True), states=[state]).get(
        "/admin/users/member%40taxconsulting.co.za/sync-status",
        headers={"Authorization": "Bearer mock:admin@taxconsulting.co.za"},
    )
    assert response.status_code == 200
    assert response.json() == [{
        "source": "calendar", "status": "failed",
        "last_attempted_at": "2026-09-15T00:00:00+00:00",
        "last_succeeded_at": None, "last_error": "Graph request failed",
    }]
    assert "token" not in response.text.lower()


def test_non_admin_cannot_retrieve_another_users_diagnostics():
    response = _client(_user(False)).get(
        "/admin/users/member%40taxconsulting.co.za/sync-status",
        headers={"Authorization": "Bearer mock:member@taxconsulting.co.za"},
    )
    assert response.status_code == 403


def test_unknown_user_returns_404():
    response = _client(_user(True), target=None).get(
        "/admin/users/missing%40taxconsulting.co.za/sync-status",
        headers={"Authorization": "Bearer mock:admin@taxconsulting.co.za"},
    )
    assert response.status_code == 404
