"""Offline admin authorization, validation, projection and keyset contracts."""
import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.api.admin import router
from app.db import get_db
from app.models import AuditEvent
from app.services.audit_queries import query_audit_events, safe_metadata


def row(**overrides):
    values = dict(id=uuid4(), occurred_at=datetime(2026, 10, 6, 10, tzinfo=timezone.utc),
                  event_type="recording.processing", outcome="failed", actor_type="system",
                  actor_id="recording_worker", actor_upn=None, resource_type="recording_job",
                  resource_id=uuid4(), meeting_id=None, job_id=None, correlation_id=uuid4(),
                  event_metadata={"attempt": 1, "retry_scheduled": True,
                                  "error_category": "processing_error"})
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def api():
    db = MagicMock()
    db.scalar = AsyncMock(return_value=SimpleNamespace(is_admin=True))
    result = MagicMock()
    result.all.return_value = [row()]
    db.scalars = AsyncMock(return_value=result)
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, db, {"Authorization": "Bearer mock:admin@taxconsulting.co.za"}


def test_admin_response_is_safe_and_not_cached(api):
    client, db, headers = api
    item = row(event_metadata={"attempt": 1, "retry_scheduled": True,
                              "source": "SECRET", "reason": "token=SECRET",
                              "transcript": "SECRET", "error_category": "https://SECRET"})
    item.actor_entra_oid = "SECRET"
    item.event_key = "SECRET"
    db.scalars.return_value.all.return_value = [item]
    response = client.get("/admin/audit-events", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "SECRET" not in response.text
    body = response.json()
    assert body["items"][0]["metadata"] == {"attempt": 1, "retry_scheduled": True}
    assert body["next_cursor"] is None and body["has_more"] is False
    assert set(body["items"][0]) == {"id", "occurred_at", "event_type", "outcome",
        "actor_type", "actor_id", "actor_upn", "resource_type", "resource_id",
        "meeting_id", "job_id", "correlation_id", "metadata"}


@pytest.mark.parametrize("admin,status", [(False, 403), (None, 403)])
def test_nonadmin_and_unregistered_denied(api, admin, status):
    client, db, headers = api
    db.scalar.return_value = SimpleNamespace(is_admin=admin) if admin is not None else None
    assert client.get("/admin/audit-events", headers=headers).status_code == status
    db.scalars.assert_not_awaited()


def test_missing_auth_denied(api):
    client, db, _ = api
    assert client.get("/admin/audit-events").status_code == 401
    db.scalars.assert_not_awaited()


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 101}, {"limit": "abc"},
    {"from": "yesterday"}, {"from": "2026-10-01T00:00:00"},
    {"from": "2026-10-06T00:00:00Z", "to": "2026-10-05T00:00:00Z"},
    {"from": "2026-01-01T00:00:00Z", "to": "2026-10-06T00:00:00Z"},
    {"outcome": "sent"}, {"actor_type": "admin"}, {"actor_upn": "bad"},
    {"actor_id": " "}, {"event_type": "recording"},
    {"cursor": "!"}, {"cursor": "a" * 2049},
])
def test_invalid_queries_rejected_before_history_query(api, params):
    client, db, headers = api
    assert client.get("/admin/audit-events", params=params, headers=headers).status_code == 422
    db.scalars.assert_not_awaited()


def test_filters_are_exact_bounded_and_parameterized(api):
    client, db, headers = api
    response = client.get("/admin/audit-events", headers=headers, params={
        "from": "2026-10-01T08:00:00+08:00", "to": "2026-10-07T00:00:00Z",
        "event_type": "recording.processing", "outcome": "failed", "actor_type": "user",
        "actor_upn": "ADMIN@TAXCONSULTING.CO.ZA", "actor_id": str(uuid4()), "limit": 10})
    assert response.status_code == 200
    compiled = db.scalars.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "ORDER BY audit_events.occurred_at DESC, audit_events.id DESC" in sql
    assert "OFFSET" not in sql and "JOIN" not in sql
    assert "admin@taxconsulting.co.za" in compiled.params.values()
    assert 11 in compiled.params.values()
    assert response.json()["window_start"] == "2026-10-01T00:00:00Z"


async def test_cursor_reuses_window_rejects_changed_filters_and_invalid_boundary():
    db = MagicMock()
    db.scalars = AsyncMock(return_value=MagicMock())
    first, extra = row(), row()
    db.scalars.return_value.all.return_value = [first, extra]
    page = await query_audit_events(db, limit=1, outcome="failed",
        start=first.occurred_at - timedelta(days=1), end=first.occurred_at + timedelta(days=1))
    assert page.has_more and page.next_cursor
    db.scalars.return_value.all.return_value = []
    next_page = await query_audit_events(db, cursor=page.next_cursor, outcome="failed")
    assert next_page.window_start == page.window_start and next_page.window_end == page.window_end
    compiled = db.scalars.await_args.args[0].compile(dialect=postgresql.dialect())
    assert "(audit_events.occurred_at, audit_events.id) <" in str(compiled)
    with pytest.raises(ValueError):
        await query_audit_events(db, cursor=page.next_cursor, outcome="succeeded")
    with pytest.raises(ValueError):
        await query_audit_events(db, cursor=page.next_cursor, outcome="failed",
                                 start=page.window_start - timedelta(days=1))
    payload = json.loads(base64.urlsafe_b64decode(page.next_cursor + "=" * (-len(page.next_cursor) % 4)))
    payload["time"] = "2000-01-01T00:00:00+00:00"
    bad_cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(ValueError):
        await query_audit_events(db, cursor=bad_cursor, outcome="failed")


def test_metadata_is_typed_and_fail_closed():
    parent = uuid4()
    assert safe_metadata({"parent_job_id": str(parent), "attempt": True, "recipient_count": -1,
        "retry_scheduled": "true", "source": "manual", "reason": "raw SECRET",
        "fingerprint": "SECRET", "drive_id": "SECRET"}) == {
        "parent_job_id": str(parent), "source": "manual"}
    assert safe_metadata(None) == {} and safe_metadata({"parent_job_id": "invalid"}) == {}


async def test_real_query_paginates_equal_timestamps_without_duplicates():
    # Isolated in-memory test table only; production schema/defaults are untouched.
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""CREATE TABLE audit_events (
            id TEXT PRIMARY KEY, occurred_at DATETIME, event_type VARCHAR(64), outcome VARCHAR(16),
            actor_type VARCHAR(16), actor_id VARCHAR(64), actor_upn VARCHAR(255), actor_entra_oid VARCHAR(64),
            resource_type VARCHAR(32), resource_id TEXT, meeting_id TEXT, job_id TEXT,
            correlation_id TEXT, event_key VARCHAR(255), metadata JSON)"""))
    with Session(engine, expire_on_commit=False) as sync:
        stamp = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)
        for number in range(1, 8):
            values = vars(row(id=UUID(int=number), occurred_at=stamp))
            sync.add(AuditEvent(**values, event_key=str(number)))
        sync.commit()

        class Adapter:
            async def scalars(self, query):
                result = sync.scalars(query).all()
                # SQLite loses timezone information; PostgreSQL timestamptz retains it.
                for event in result:
                    if event.occurred_at.tzinfo is None:
                        event.occurred_at = event.occurred_at.replace(tzinfo=timezone.utc)
                return SimpleNamespace(all=lambda: result)

        ids, cursor = [], None
        for _ in range(4):
            page = await query_audit_events(Adapter(), start=stamp - timedelta(days=1),
                end=stamp + timedelta(days=1), limit=2, cursor=cursor)
            ids.extend(item.id.int for item in page.items)
            cursor = page.next_cursor
            if not cursor:
                break
        assert ids == list(range(7, 0, -1))
    engine.dispose()
