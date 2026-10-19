"""Calendar-only manual operation with fake DB sessions and mocked Graph reads."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api import calendar
from app.db import get_db
from app.models import RegisteredUser, SyncedCalendarEvent
from app.services import calendar_sync as service


COUNTS = {"status": "success", "succeeded": 3, "failed": 0, "skipped": 0,
          "created": 2, "updated": 4}


def context(value):
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=value)
    manager.__aexit__ = AsyncMock(return_value=False)
    return manager


def session():
    db = MagicMock()
    db.scalar = AsyncMock()
    db.scalars = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def connection(acquired=True):
    conn = SimpleNamespace(scalar=AsyncMock(return_value=acquired),
                           commit=AsyncMock(), execute=AsyncMock(), invalidate=AsyncMock())
    return conn


@pytest.fixture
async def endpoint():
    db = session()
    db.scalar.return_value = RegisteredUser(
        upn="admin@taxconsulting.co.za", is_admin=True, is_subscribed=True, entra_oid="existing-oid",
    )
    app = FastAPI()
    app.include_router(calendar.router)

    async def local_db():
        yield db

    app.dependency_overrides[get_db] = local_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline.test") as client:
        yield client, db


HEADERS = {"Authorization": "Bearer mock:admin@taxconsulting.co.za"}


async def test_endpoint_requires_authentication(endpoint, monkeypatch):
    client, _ = endpoint
    sync = AsyncMock()
    monkeypatch.setattr(calendar, "sync_subscribed_calendars_once", sync)
    response = await client.post("/calendar/sync", json={})
    assert response.status_code == 401
    sync.assert_not_awaited()


@pytest.mark.parametrize("admin,subscribed", [(False, True), (True, False), (False, False)])
async def test_endpoint_requires_existing_subscribed_admin(endpoint, monkeypatch, admin, subscribed):
    client, db = endpoint
    db.scalar.return_value.is_admin = admin
    db.scalar.return_value.is_subscribed = subscribed
    sync = AsyncMock()
    monkeypatch.setattr(calendar, "sync_subscribed_calendars_once", sync)
    response = await client.post("/calendar/sync", json={}, headers=HEADERS)
    assert response.status_code == 403
    sync.assert_not_awaited()


async def test_endpoint_accepts_one_explicit_run_with_schedule_disabled(endpoint, monkeypatch):
    from app.config import get_settings

    client, _ = endpoint
    monkeypatch.setattr(get_settings(), "enable_scheduled_sync", False)
    sync = AsyncMock(return_value=COUNTS)
    monkeypatch.setattr(calendar, "sync_subscribed_calendars_once", sync)
    response = await client.post("/calendar/sync", json={}, headers=HEADERS)
    assert response.status_code == 200 and response.json() == COUNTS
    sync.assert_awaited_once_with()
    assert get_settings().enable_scheduled_sync is False


async def test_endpoint_rejects_caller_supplied_targets(endpoint, monkeypatch):
    client, _ = endpoint
    sync = AsyncMock()
    monkeypatch.setattr(calendar, "sync_subscribed_calendars_once", sync)
    response = await client.post("/calendar/sync", json={"users": ["outside@example.test"]}, headers=HEADERS)
    assert response.status_code == 422
    sync.assert_not_awaited()


async def test_endpoint_hides_infrastructure_errors(endpoint, monkeypatch):
    client, _ = endpoint
    sync = AsyncMock(side_effect=RuntimeError("SECRET database credentials"))
    monkeypatch.setattr(calendar, "sync_subscribed_calendars_once", sync)
    response = await client.post("/calendar/sync", json={}, headers=HEADERS)
    assert response.status_code == 503 and "SECRET" not in response.text
    sync.assert_awaited_once()


async def test_concurrent_endpoint_request_is_rejected_without_starting_a_second_sync(endpoint, monkeypatch):
    client, _ = endpoint
    first, second = connection(), connection(False)
    monkeypatch.setattr(service, "engine", SimpleNamespace(connect=MagicMock(
        side_effect=[context(first), context(second)],
    )))
    started, release = asyncio.Event(), asyncio.Event()

    async def waiting():
        started.set()
        await release.wait()
        return COUNTS

    sync = AsyncMock(side_effect=waiting)
    monkeypatch.setattr(service, "_sync_subscribers", sync)
    pending = asyncio.create_task(client.post("/calendar/sync", json={}, headers=HEADERS))
    try:
        await asyncio.wait_for(started.wait(), 1)
        duplicate = await client.post("/calendar/sync", json={}, headers=HEADERS)
        assert duplicate.status_code == 409
    finally:
        release.set()
    response = await pending
    assert response.status_code == 200
    sync.assert_awaited_once()
    assert "pg_advisory_unlock" in str(first.execute.await_args.args[0])
    second.execute.assert_not_awaited()


async def test_subscriber_scope_counts_failures_and_no_recording_side_effects(monkeypatch):
    from app.services import jobs
    from app.workers import reconcile
    from app.ai import runtime_bridge

    ids = [uuid4() for _ in range(5)]
    snapshot = session()
    snapshot.scalars.return_value = SimpleNamespace(all=lambda: ids)
    rows = [session() for _ in ids]
    users = [RegisteredUser(id=ids[i], upn=f"subscriber{i}@taxconsulting.co.za",
                            is_subscribed=True, entra_oid=f"oid-{i}") for i in range(3)]
    existing = SyncedCalendarEvent(user_upn=users[1].upn, event_id="old", raw={})
    rows[0].scalar.side_effect = [users[0], None]
    rows[1].scalar.side_effect = [users[1], existing]
    rows[2].scalar.return_value = users[2]
    # No Entra link / opted out after snapshot: the guarded DB query returns no row.
    rows[3].scalar.return_value = rows[4].scalar.return_value = None
    monkeypatch.setattr(service, "SessionLocal", MagicMock(side_effect=[context(db) for db in [snapshot, *rows]]))
    state = AsyncMock()
    monkeypatch.setattr(service, "record_sync_result", state)
    graph = AsyncMock(side_effect=[
        [{"id": "new", "subject": "Synthetic", "start": {}, "end": {}}],
        [{"id": "old", "subject": "Synthetic", "start": {}, "end": {}}],
        httpx.HTTPStatusError("SECRET upstream body", request=httpx.Request("GET", "https://offline.invalid"),
                              response=httpx.Response(403)),
    ])
    monkeypatch.setattr(service.graph, "get_upcoming_calendar_events", graph)
    forbidden = AsyncMock(side_effect=AssertionError("Recording/AI/mail side effect"))
    monkeypatch.setattr(jobs, "enqueue_recording_job", forbidden)
    monkeypatch.setattr(reconcile, "reconcile", forbidden)
    monkeypatch.setattr(service.graph, "send_mail", forbidden)
    monkeypatch.setattr(runtime_bridge, "process", forbidden)
    conn = connection()
    monkeypatch.setattr(service, "engine", SimpleNamespace(connect=lambda: context(conn)))

    result = await service.sync_subscribed_calendars_once()
    assert result == {"status": "partial", "succeeded": 2, "failed": 1, "skipped": 2,
                      "created": 1, "updated": 1}
    assert graph.await_count == 3
    assert [call.args[0] for call in graph.await_args_list] == [u.upn for u in users]
    assert all(call.kwargs == {"days": 14, "include_offline": True} for call in graph.await_args_list)
    assert "is_subscribed IS true" in str(snapshot.scalars.await_args.args[0])
    for db in rows:
        sql = str(db.scalar.await_args_list[0].args[0])
        assert "is_subscribed IS true" in sql and "entra_oid IS NOT NULL" in sql and "FOR UPDATE" in sql
        assert all(isinstance(call.args[0], SyncedCalendarEvent) for call in db.add.call_args_list)
    rows[2].rollback.assert_awaited_once()
    assert "SECRET" not in str(state.await_args_list) and "SECRET" not in str(result)
    forbidden.assert_not_awaited()


async def test_failed_run_returns_safe_counts_without_retry(monkeypatch):
    db, per_user = session(), session()
    db.scalars.return_value = SimpleNamespace(all=lambda: [uuid4()])
    per_user.scalar.return_value = RegisteredUser(upn="subscribed@taxconsulting.co.za")
    monkeypatch.setattr(service, "SessionLocal", MagicMock(side_effect=[context(db), context(per_user)]))
    monkeypatch.setattr(service, "record_sync_result", AsyncMock())
    fetch = AsyncMock(side_effect=TimeoutError("SECRET"))
    monkeypatch.setattr(service.graph, "get_upcoming_calendar_events", fetch)
    result = await service._sync_subscribers()
    assert result["status"] == "failed" and result["failed"] == 1
    assert result["created"] == result["updated"] == 0
    fetch.assert_awaited_once()


async def test_cancellation_releases_lock(monkeypatch):
    conn = connection()
    monkeypatch.setattr(service, "engine", SimpleNamespace(connect=lambda: context(conn)))
    monkeypatch.setattr(service, "_sync_subscribers", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await service.sync_subscribed_calendars_once()
    assert "pg_advisory_unlock" in str(conn.execute.await_args.args[0])


async def test_no_active_subscribers_does_not_read_graph(monkeypatch):
    db = session()
    db.scalars.return_value = SimpleNamespace(all=lambda: [])
    monkeypatch.setattr(service, "SessionLocal", lambda: context(db))
    fetch = AsyncMock(side_effect=AssertionError("No subscriber is eligible"))
    monkeypatch.setattr(service.graph, "get_upcoming_calendar_events", fetch)
    result = await service._sync_subscribers()
    assert result == {"status": "success", "succeeded": 0, "failed": 0, "skipped": 0,
                      "created": 0, "updated": 0}
    fetch.assert_not_awaited()
