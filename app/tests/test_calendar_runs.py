"""Real local transactions, fake Microsoft reads, no production transports."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    BusinessUnit,
    CalendarSyncRun,
    RegisteredUser,
    SyncedCalendarEvent,
    UserSyncState,
)
from app.services import calendar_runs as runs
from app.services import calendar_sync as sync


class LocalSession:
    def __init__(self, engine):
        self.session = Session(engine, expire_on_commit=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.session.close()

    async def get(self, *args, **kwargs):
        return self.session.get(*args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return self.session.scalar(*args, **kwargs)

    async def scalars(self, *args, **kwargs):
        return self.session.scalars(*args, **kwargs)

    def add(self, row):
        self.session.add(row)

    async def commit(self):
        self.session.commit()

    async def rollback(self):
        self.session.rollback()


@pytest.fixture
async def local(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (BusinessUnit, RegisteredUser, CalendarSyncRun, SyncedCalendarEvent, UserSyncState):
        model.__table__.create(engine)
    factory = lambda: LocalSession(engine)
    monkeypatch.setattr(runs, "SessionLocal", factory)
    monkeypatch.setattr(sync, "SessionLocal", factory)
    lock = asyncio.Lock()

    @asynccontextmanager
    async def exclusive():
        if lock.locked():
            raise sync.CalendarSyncBusy()
        async with lock:
            yield

    monkeypatch.setattr(runs, "exclusive_sync", exclusive)
    monkeypatch.setattr(runs, "_tasks", {})
    runs.start_lifespan()
    with Session(engine) as db:
        users = [RegisteredUser(id=uuid4(), upn=f"synthetic-{i}@example.test", is_admin=True,
                                is_subscribed=True, entra_oid=f"oid-{i}") for i in range(2)]
        db.add_all(users)
        db.commit()
        ids = [user.id for user in users]
    graph = AsyncMock(return_value=[{"id": "event", "subject": "Synthetic", "start": {}, "end": {}}])
    monkeypatch.setattr(sync.graph, "get_upcoming_calendar_events", graph)
    yield SimpleNamespace(engine=engine, ids=ids, graph=graph, lock=lock)
    await runs.shutdown()
    engine.dispose()


async def settled(run_id):
    task = runs._tasks.get(run_id)
    if task is not None:
        await task
    return await runs.get_run(run_id)


async def test_submission_is_durable_and_idempotent_while_work_is_pending(local):
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return []

    local.graph.side_effect = slow
    run_id = uuid4()
    first = await runs.submit(run_id, local.ids[0])
    assert first["status"] == "queued"
    await entered.wait()
    assert (await runs.get_run(run_id))["status"] == "running"
    assert (await runs.submit(run_id, local.ids[0]))["id"] == run_id
    assert (await runs.submit(uuid4(), local.ids[0]))["id"] == run_id
    assert len(runs._tasks) == 1
    release.set()
    result = await settled(run_id)
    assert result["status"] == "success" and result["succeeded"] == 2
    calls = local.graph.await_count
    assert (await runs.submit(run_id, local.ids[0]))["status"] == "success"
    assert local.graph.await_count == calls


async def test_counts_and_calendar_rows_commit_together_and_refresh_is_not_insert(local):
    first_id = uuid4()
    await runs.submit(first_id, local.ids[0])
    first = await settled(first_id)
    assert (first["created"], first["updated"], first["succeeded"]) == (2, 0, 2)
    second_id = uuid4()
    await runs.submit(second_id, local.ids[0])
    second = await settled(second_id)
    assert (second["created"], second["updated"], second["succeeded"]) == (0, 2, 2)
    with Session(local.engine) as db:
        assert len(db.scalars(select(SyncedCalendarEvent)).all()) == 2


async def test_write_failure_rolls_back_user_and_reports_unknown_instead_of_retry(local, monkeypatch):
    original = runs.progress
    calls = 0

    async def broken_commit(db, run_id, **counts):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("SECRET database response")
        await original(db, run_id, **counts)

    monkeypatch.setattr(runs, "progress", broken_commit)
    run_id = uuid4()
    await runs.submit(run_id, local.ids[0])
    result = await settled(run_id)
    assert result["status"] == "unknown" and result["retry_allowed"] is False
    assert result["created"] == result["succeeded"] == 1
    assert result["error_category"] == "infrastructure_unconfirmed"
    with Session(local.engine) as db:
        assert len(db.scalars(select(SyncedCalendarEvent)).all()) == 1
        assert len(db.scalars(select(UserSyncState)).all()) == 1
    assert (await runs.submit(uuid4(), local.ids[0]))["id"] == run_id
    assert "SECRET" not in str(result)


async def test_graph_failure_is_safe_partial_result_and_not_retried(local):
    local.graph.side_effect = [RuntimeError("SECRET vendor response"), []]
    run_id = uuid4()
    await runs.submit(run_id, local.ids[0])
    result = await settled(run_id)
    assert result["status"] == "partial"
    assert (result["failed"], result["succeeded"]) == (1, 1)
    assert local.graph.await_count == 2
    assert "SECRET" not in str(result)


async def test_shutdown_after_one_commit_preserves_progress_and_blocks_retry(local):
    entered = asyncio.Event()
    calls = 0

    async def slow_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            await asyncio.Event().wait()
        return [{"id": "event", "start": {}, "end": {}}]

    local.graph.side_effect = slow_second
    run_id = uuid4()
    await runs.submit(run_id, local.ids[0])
    await entered.wait()
    await runs.shutdown()
    result = await runs.get_run(run_id)
    assert result["status"] == "unknown" and result["error_category"] == "interrupted"
    assert result["created"] == result["succeeded"] == 1
    assert not runs._tasks
    assert not local.lock.locked()


async def test_stale_run_is_unknown_after_restart_without_starting_work(local):
    run_id = uuid4()
    with Session(local.engine) as db:
        db.add(CalendarSyncRun(id=run_id, requested_by=local.ids[0], status="running",
                               heartbeat_at=runs.now() - timedelta(seconds=120)))
        db.commit()
    result = await runs.get_run()
    assert result["status"] == "unknown" and result["error_category"] == "owner_unavailable"
    assert (await runs.submit(uuid4(), local.ids[0]))["id"] == run_id
    local.graph.assert_not_awaited()


async def test_legacy_sync_lock_rejects_submission_before_work_is_created(local):
    async with local.lock:
        with pytest.raises(sync.CalendarSyncBusy):
            await runs.submit(uuid4(), local.ids[0])
    assert await runs.get_run() is None
    local.graph.assert_not_awaited()


async def test_heartbeat_failure_cancels_work_and_preserves_unknown(local, monkeypatch):
    async def broken_heartbeat(run_id):
        raise RuntimeError("SECRET connection failure")

    monkeypatch.setattr(runs, "heartbeat", broken_heartbeat)
    async def waiting(*args, **kwargs):
        await asyncio.Event().wait()

    local.graph.side_effect = waiting
    run_id = uuid4()
    await runs.submit(run_id, local.ids[0])
    result = await settled(run_id)
    assert result["status"] == "unknown" and not result["retry_allowed"]


async def test_lost_http_confirmation_does_not_orphan_the_tracked_run(local):
    from fastapi import FastAPI
    from uvicorn.protocols.http.h11_impl import RequestResponseCycle

    from app.api.calendar import router
    from app.api.deps import registered_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[registered_user] = lambda: RegisteredUser(
        id=local.ids[0], is_admin=True, is_subscribed=True,
    )
    run_id = uuid4()
    body = f'{{"request_id":"{run_id}"}}'.encode()
    sent_request = False

    async def receive():
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    # Actual installed Uvicorn discards responses once disconnected, without
    # cancelling app execution or emitting a POST access-log completion line.
    cycle = object.__new__(RequestResponseCycle)
    cycle.disconnected = True
    cycle.flow = SimpleNamespace(write_paused=False)
    await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
               "method": "POST", "scheme": "http", "path": "/calendar/sync", "raw_path": b"/calendar/sync",
               "query_string": b"", "root_path": "", "headers": [(b"content-type", b"application/json")],
               "client": ("offline", 0), "server": ("offline", 0)}, receive, cycle.send)
    result = await settled(run_id)
    assert result["status"] == "success" and result["created"] == 2


async def test_legacy_request_can_commit_after_disconnect_without_access_log(local):
    from fastapi import FastAPI
    from uvicorn.protocols.http.h11_impl import RequestResponseCycle

    app = FastAPI()

    @app.post("/legacy-sync")
    async def legacy():
        return await sync._sync_subscribers()

    async def receive():
        return {"type": "http.disconnect"}

    cycle = object.__new__(RequestResponseCycle)
    cycle.disconnected = True
    cycle.flow = SimpleNamespace(write_paused=False)
    await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
               "method": "POST", "scheme": "http", "path": "/legacy-sync", "raw_path": b"/legacy-sync",
               "query_string": b"", "root_path": "", "headers": [],
               "client": ("offline", 0), "server": ("offline", 0)}, receive, cycle.send)
    with Session(local.engine) as db:
        assert len(db.scalars(select(SyncedCalendarEvent)).all()) == 2
    local.graph.assert_awaited()


async def test_calendar_token_acquisition_does_not_run_on_event_loop(monkeypatch):
    import threading

    import httpx

    from app.graph import client

    loop_thread = threading.get_ident()

    def headers():
        assert threading.get_ident() != loop_thread
        return {"Authorization": "Bearer offline-token"}

    monkeypatch.setattr(client, "_headers", headers)
    monkeypatch.setattr(client.settings, "graph_base", "https://offline.invalid")
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"value": []}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport, **kwargs))
    assert await client._calendar_pages("https://offline.invalid/calendar") == []


async def test_auth_key_refresh_does_not_run_on_event_loop(monkeypatch):
    import threading

    from fastapi.security import HTTPAuthorizationCredentials

    from app.api import deps

    loop_thread = threading.get_ident()

    def validate(token):
        assert threading.get_ident() != loop_thread
        return {"preferred_username": "synthetic@example.test", "oid": "offline-oid"}

    monkeypatch.setattr(deps.settings, "auth_mode", "entra")
    monkeypatch.setattr(deps.settings, "allowed_domain", "example.test")
    monkeypatch.setattr(deps, "validate_access_token", validate)
    db = SimpleNamespace(scalar=AsyncMock(return_value=RegisteredUser(upn="synthetic@example.test")))
    assert await deps.current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials="offline"), db) == "synthetic@example.test"


async def test_singleton_constraint_prevents_two_active_runs_without_application_lock(local):
    from sqlalchemy.exc import IntegrityError

    with Session(local.engine) as db:
        db.add_all([CalendarSyncRun(id=uuid4(), requested_by=local.ids[0]) for _ in range(2)])
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(CalendarSyncRun)) is None


async def test_cleanup_failure_cannot_overwrite_confirmed_success(local):
    run_id = uuid4()
    await runs.submit(run_id, local.ids[0])
    result = await settled(run_id)
    assert result["status"] == "success"
    await runs.mark_unknown(run_id, "infrastructure_unconfirmed")
    assert (await runs.get_run(run_id))["status"] == "success"


async def test_operation_ceiling_stops_work_without_authorizing_a_retry(local, monkeypatch):
    monkeypatch.setattr(runs, "RUN_SECONDS", 0.01)

    async def waiting(*args, **kwargs):
        await asyncio.Event().wait()

    local.graph.side_effect = waiting
    run_id = uuid4()
    await runs.submit(run_id, local.ids[0])
    result = await settled(run_id)
    assert result["status"] == "unknown" and result["error_category"] == "operation_deadline"
    assert not result["retry_allowed"] and result["created"] == 0
    assert not local.lock.locked()
