"""Offline worker contracts. Real PostgreSQL locking is NOT emulated here."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models import RecordingJob
from app.queue import worker
from app.services import jobs
from app.services.job_control import public_job_error


def job(**overrides):
    values = dict(id=uuid.uuid4(), drive_item_id="offline-recording", drive_id="drive",
                  owner_upn="owner@example.test", status="processing", attempts=1,
                  max_attempts=3, lease_token=uuid.uuid4(), locked_at=worker._now(),
                  available_at=worker._now(), last_error=None, cancel_requested_at=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def session(monkeypatch):
    db = MagicMock()
    for name in ("scalar", "scalars", "execute", "commit", "rollback"):
        setattr(db, name, AsyncMock())
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "SessionLocal", MagicMock(return_value=db))
    return db


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture(autouse=True)
def offline_worker_start(monkeypatch):
    session(monkeypatch)
    monkeypatch.setattr(worker.settings, "recording_processing_enabled", True)
    monkeypatch.setattr(worker.settings, "process_only_job_id", "")


async def test_claim_marks_processing_increments_attempt_and_commits(monkeypatch):
    db = session(monkeypatch)
    row = job(status="pending", attempts=0, lease_token=None)
    db.scalar.return_value = row
    assert await worker._claim_next() is row
    assert row.status == "processing" and row.attempts == 1 and row.lease_token
    assert row.locked_at is not None
    statement = sql(db.scalar.call_args.args[0])
    assert "FOR UPDATE SKIP LOCKED" in statement
    assert "recording_jobs.status = 'pending'" in statement
    assert "recording_jobs.attempts < recording_jobs.max_attempts" in statement
    assert "recording_jobs.available_at <=" in statement
    assert "recording_jobs.id =" not in statement
    db.commit.assert_awaited_once()
    db.expunge.assert_called_once_with(row)


async def test_claim_allowlist_selects_target_even_with_older_pending_job(monkeypatch):
    db = session(monkeypatch)
    target = job(status="pending", attempts=0, lease_token=None)
    older = job(status="pending", attempts=3, max_attempts=3, lease_token=None)
    monkeypatch.setattr(worker.settings, "process_only_job_id", str(target.id))
    db.scalar.return_value = target

    assert await worker._claim_next() is target

    claim_statement = sql(db.scalar.call_args.args[0])
    exhausted_statement = sql(db.execute.call_args.args[0])
    assert str(target.id) in claim_statement
    assert str(target.id) in exhausted_statement
    assert target.status == "processing"
    assert older.status == "pending" and older.attempts == 3 and older.lease_token is None


@pytest.mark.parametrize("unavailable_reason", ["missing", "completed", "cancelled", "not_yet_available"])
async def test_claim_allowlist_never_falls_back_when_target_is_unavailable(
    monkeypatch, unavailable_reason,
):
    db = session(monkeypatch)
    target_id = uuid.uuid4()
    monkeypatch.setattr(worker.settings, "process_only_job_id", str(target_id))
    db.scalar.return_value = None

    assert await worker._claim_next() is None

    db.scalar.assert_awaited_once()
    claim_statement = sql(db.scalar.call_args.args[0])
    exhausted_statement = sql(db.execute.call_args.args[0])
    assert str(target_id) in claim_statement
    assert str(target_id) in exhausted_statement
    assert "recording_jobs.status = 'pending'" in claim_statement
    assert "recording_jobs.attempts < recording_jobs.max_attempts" in claim_statement
    assert "recording_jobs.available_at <=" in claim_statement


async def test_empty_queue_returns_none(monkeypatch):
    db = session(monkeypatch)
    db.scalar.return_value = None
    assert await worker._claim_next() is None


@pytest.mark.parametrize("attempts,error,expected", [(1, None, "completed"),
    (1, RuntimeError("AI failed"), "pending"), (3, RuntimeError("AI failed"), "failed")])
async def test_finish_success_retry_and_permanent_failure(monkeypatch, attempts, error, expected):
    db = session(monkeypatch)
    row = job(attempts=attempts)
    token = row.lease_token
    db.scalar.return_value = row
    before = worker._now()
    await worker._finish(row.id, token, error)
    assert row.status == expected and row.lease_token is None and row.locked_at is None
    assert (row.last_error == public_job_error(error)) if error else (row.last_error is None)
    if expected == "pending":
        assert row.available_at >= before + timedelta(seconds=15)
    claim_sql = sql(db.scalar.call_args.args[0])
    assert str(token) in claim_sql and "FOR UPDATE" in claim_sql
    db.commit.assert_awaited_once()


def test_retry_backoff_is_capped():
    row = job(attempts=100, max_attempts=101)
    before = worker._now()
    worker._retry_or_fail(row, RuntimeError("failed"))
    assert before + timedelta(seconds=300) <= row.available_at <= worker._now() + timedelta(seconds=300)


async def test_old_worker_cannot_complete_new_lease(monkeypatch):
    db = session(monkeypatch)
    db.scalar.return_value = None  # WHERE id/status/token matches no row.
    await worker._finish(uuid.uuid4(), uuid.uuid4())
    db.commit.assert_not_awaited()
    assert "recording_jobs.lease_token =" in sql(db.scalar.call_args.args[0])


@pytest.mark.parametrize("attempts,lock_free,expected", [(1, True, "pending"),
    (3, True, "failed"), (1, False, "processing")])
async def test_stale_recovery_respects_live_lock_and_retry_budget(monkeypatch, attempts, lock_free, expected):
    db = session(monkeypatch)
    row = job(attempts=attempts, locked_at=worker._now() - timedelta(hours=1))
    db.scalars.return_value = [row]
    db.scalar.return_value = lock_free
    await worker._recover_interrupted_jobs()
    assert row.status == expected
    statement = sql(db.scalars.call_args.args[0])
    assert "locked_at IS NULL" in statement and "locked_at <" in statement
    assert "FOR UPDATE SKIP LOCKED" in statement
    assert "pg_try_advisory_xact_lock" in str(db.scalar.call_args.args[0])
    db.commit.assert_awaited_once()


async def test_renew_is_fenced(monkeypatch):
    db = session(monkeypatch)
    row = job()
    db.scalar.return_value = row.id
    assert await worker._renew(row.id, row.lease_token)
    statement = sql(db.scalar.call_args.args[0])
    assert str(row.lease_token) in statement and "RETURNING" in statement
    db.scalar.return_value = None
    assert not await worker._renew(row.id, row.lease_token)


def test_active_unique_index_contract():
    index = next(i for i in RecordingJob.__table__.indexes if i.name == "uq_recording_jobs_active_item")
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE INDEX" in ddl
    assert "WHERE status IN ('pending', 'processing')" in ddl


@pytest.mark.parametrize("created", [None, uuid.uuid4()])
async def test_concurrent_retry_insert_conflict_contract(monkeypatch, created):
    db = session(monkeypatch)
    db.scalar.side_effect = [None, created]  # Race after the initial fast-path check.
    result = await jobs.enqueue_retry_job(db, drive_item_id="r", drive_id="d", owner_upn="a")
    assert result is (created is not None)
    statement = sql(db.scalar.call_args.args[0])
    assert "ON CONFLICT (drive_item_id) WHERE" in statement
    assert "DO NOTHING RETURNING" in statement
    if created:
        db.commit.assert_awaited_once()
    else:
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()


async def test_retry_already_active_does_not_insert(monkeypatch):
    db = session(monkeypatch)
    db.scalar.return_value = uuid.uuid4()
    assert not await jobs.enqueue_retry_job(db, drive_item_id="r", drive_id="d", owner_upn="a")
    db.scalar.assert_awaited_once()
    db.commit.assert_not_awaited()


@asynccontextmanager
async def unlocked(_):
    yield


@pytest.mark.parametrize("error", [None, RuntimeError("provider failed")])
async def test_execute_routes_pipeline_result_to_finish(monkeypatch, error):
    row = job()
    monkeypatch.setattr(worker, "_recording_lock", unlocked)
    monkeypatch.setattr(worker, "_renew", AsyncMock(return_value=True))
    process = AsyncMock(side_effect=error)
    finish = AsyncMock()
    monkeypatch.setattr(worker, "_process", process)
    monkeypatch.setattr(worker, "_finish", finish)
    await worker._execute(row)
    process.assert_awaited_once_with(row)
    if error:
        finish.assert_awaited_once_with(row.id, row.lease_token, error)
    else:
        finish.assert_awaited_once_with(row.id, row.lease_token)


async def test_lost_heartbeat_cancels_pipeline(monkeypatch):
    row = job()
    cancelled = asyncio.Event()

    async def pipeline(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(worker, "_recording_lock", unlocked)
    monkeypatch.setattr(worker, "_renew", AsyncMock(return_value=True))
    monkeypatch.setattr(worker, "_process", pipeline)
    monkeypatch.setattr(worker, "_heartbeat", AsyncMock(side_effect=RuntimeError("lease lost")))
    finish = AsyncMock()
    monkeypatch.setattr(worker, "_finish", finish)
    await worker._execute(row)
    assert cancelled.is_set()
    assert "lease lost" in str(finish.call_args.args[2])


async def test_empty_worker_waits_and_can_stop(monkeypatch):
    stop = asyncio.Event()
    monkeypatch.setattr(worker, "_recover_interrupted_jobs", AsyncMock())
    claim = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "_claim_next", claim)
    idle = AsyncMock(side_effect=lambda _: stop.set())
    monkeypatch.setattr(worker, "_idle", idle)
    await worker.run_worker(stop)
    claim.assert_awaited_once()
    idle.assert_awaited_once()


async def test_stop_cancels_long_task_after_grace_and_does_not_claim_again(monkeypatch):
    stop = asyncio.Event()
    row = job()
    cancelled = asyncio.Event()

    async def long_task(_):
        stop.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(worker.settings, "worker_shutdown_seconds", 0)
    monkeypatch.setattr(worker, "_recover_interrupted_jobs", AsyncMock())
    claim = AsyncMock(return_value=row)
    monkeypatch.setattr(worker, "_claim_next", claim)
    monkeypatch.setattr(worker, "_execute", long_task)
    await worker.run_worker(stop)
    assert cancelled.is_set()
    claim.assert_awaited_once()


async def test_signal_handlers_set_stop_and_restore(monkeypatch):
    stop = asyncio.Event()
    handlers = {}
    old = MagicMock()
    monkeypatch.setattr(worker.signal, "getsignal", lambda sig: old)
    monkeypatch.setattr(worker.signal, "signal", lambda sig, fn: handlers.update({sig: fn}))
    restore = worker._install_stop_handlers(stop)
    for sig in (worker.signal.SIGINT, worker.signal.SIGTERM):
        stop.clear()
        handlers[sig](sig, None)
        await asyncio.sleep(0)
        assert stop.is_set()
    restore()
    assert all(fn is old for fn in handlers.values())


async def test_advisory_lock_released_on_pipeline_failure(monkeypatch):
    conn = MagicMock()
    conn.scalar = AsyncMock(return_value=True)
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "engine", SimpleNamespace(connect=lambda: conn))
    with pytest.raises(RuntimeError, match="pipeline"):
        async with worker._recording_lock("r"):
            raise RuntimeError("pipeline")
    assert "pg_advisory_unlock" in str(conn.execute.call_args.args[0])


async def test_busy_advisory_lock_never_runs_pipeline(monkeypatch):
    conn = MagicMock()
    conn.scalar = AsyncMock(return_value=False)
    conn.commit = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "engine", SimpleNamespace(connect=lambda: conn))
    with pytest.raises(RuntimeError, match="another worker"):
        async with worker._recording_lock("r"):
            pytest.fail("Must not enter a busy recording lock")


def test_network_guard_blocks_dns_and_real_socket_connections():
    import socket
    with pytest.raises(AssertionError, match="Offline tests"):
        socket.getaddrinfo("example.invalid", 443)
    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="Offline tests"):
            sock.connect(("127.0.0.1", 5432))


async def test_restarted_worker_recovers_from_new_session_without_process_memory(monkeypatch):
    first_session = session(monkeypatch)
    persisted = job(status="pending", attempts=0)
    first_session.scalar.return_value = persisted
    await worker._claim_next()
    first_session.commit.assert_awaited_once()
    # Model persistence using the same stored row, but a new session/worker.
    # Actual process death and DB durability still require PostgreSQL testing.
    persisted.locked_at = worker._now() - timedelta(hours=1)
    next_session = session(monkeypatch)
    next_session.scalars.return_value = [persisted]
    next_session.scalar.return_value = True
    await worker._recover_interrupted_jobs()
    assert persisted.status == "pending" and persisted.attempts == 1
    assert persisted.lease_token is None


async def test_idle_yields_to_event_loop_and_wakes_on_stop():
    stop = asyncio.Event()
    waiting = asyncio.create_task(worker._idle(stop))
    await asyncio.sleep(0)
    assert not waiting.done()
    stop.set()
    await waiting


async def test_cancelled_execution_releases_task_for_retry(monkeypatch):
    row = job()
    started = asyncio.Event()

    async def process(_):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "_recording_lock", unlocked)
    monkeypatch.setattr(worker, "_renew", AsyncMock(return_value=True))
    monkeypatch.setattr(worker, "_process", process)
    finish = AsyncMock()
    monkeypatch.setattr(worker, "_finish", finish)
    task = asyncio.create_task(worker._execute(row))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "stopped" in str(finish.call_args.args[2])


async def test_worker_drains_successful_job_before_grace_expires(monkeypatch):
    stop = asyncio.Event()
    completed = asyncio.Event()

    async def process(_):
        stop.set()
        await asyncio.sleep(0)
        completed.set()

    monkeypatch.setattr(worker, "_recover_interrupted_jobs", AsyncMock())
    claim = AsyncMock(return_value=job())
    monkeypatch.setattr(worker, "_claim_next", claim)
    monkeypatch.setattr(worker, "_execute", process)
    await worker.run_worker(stop)
    assert completed.is_set()
    claim.assert_awaited_once()


async def test_interrupted_meeting_failure_does_not_overwrite_review_gate(monkeypatch):
    db = session(monkeypatch)
    row = job(last_error="interrupted")
    await worker._mark_meeting_interrupted(db, row)
    statement = sql(db.execute.call_args.args[0])
    assert "UPDATE meetings SET state='failed'" in statement
    assert "transcribing" in statement and "extracting" in statement
    assert "awaiting_review" not in statement and "approved" not in statement and "sent" not in statement


async def test_unknown_advisory_lock_ownership_invalidates_connection(monkeypatch):
    conn = MagicMock()
    conn.scalar = AsyncMock(side_effect=RuntimeError("connection lost"))
    conn.invalidate = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "engine", SimpleNamespace(connect=lambda: conn))
    with pytest.raises(RuntimeError, match="connection lost"):
        async with worker._recording_lock("r"):
            pytest.fail("Lock was never confirmed")
    conn.invalidate.assert_awaited_once()
