"""Offline contracts for audit staging at fenced outcome commits."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models import AuditEvent
from app.pipeline import steps
from app.queue import worker
from app.services.job_control import guarded_commit, JobCancelled


def job(**overrides):
    values = dict(id=uuid4(), source="manual", attempts=1, max_attempts=3,
                  status="processing", lease_token=uuid4(), cancel_requested_at=None,
                  locked_at=worker._now(), drive_item_id="item", last_error=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def session(monkeypatch, row=None):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=row)
    db.scalars = AsyncMock(return_value=[])
    db.execute = AsyncMock(return_value=MagicMock())
    db.execute.return_value.scalars.return_value = []
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    return db


def events(db):
    return [call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditEvent)]


@pytest.mark.parametrize("attempt", [1, 3])
async def test_failure_is_staged_with_retry_decision_and_sanitized(monkeypatch, attempt):
    row = job(attempts=attempt)
    db = session(monkeypatch, row)
    token = row.lease_token

    async def commit():
        event, = events(db)
        assert event.event_type == "recording.processing" and event.outcome == "failed"
        assert event.actor_type == "system" and event.actor_id == "recording_worker"
        assert event.resource_type == "recording_job"
        assert event.resource_id == event.correlation_id == event.job_id == row.id
        assert event.event_metadata["retry_scheduled"] == (attempt < 3)
        assert event.event_metadata["new_state"] == row.status
        assert "SECRET" not in str(event.event_metadata)

    db.commit.side_effect = commit
    await worker._finish(row.id, token, RuntimeError("https://private?token=SECRET"))
    db.commit.assert_awaited_once()


async def test_success_staged_after_fence_with_same_commit(monkeypatch):
    row = job()
    db = session(monkeypatch, row)

    async def commit():
        event, = events(db)
        assert row.status == "completed" and row.lease_token is None
        assert event.outcome == "succeeded" and event.event_metadata["attempt"] == 1

    db.commit.side_effect = commit
    await guarded_commit(db, row.id, row.lease_token, complete=True)
    db.commit.assert_awaited_once()
    # A subsequent worker finish cannot match a completed job's processing lease.
    db.scalar.return_value = None
    await worker._finish(row.id, uuid4())
    assert len(events(db)) == 1
    db.commit.assert_awaited_once()


async def test_lost_fence_never_stages_success(monkeypatch):
    db = session(monkeypatch)
    with pytest.raises(JobCancelled):
        await guarded_commit(db, uuid4(), uuid4(), complete=True)
    assert not events(db)
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


async def test_intermediate_commit_has_no_outcome(monkeypatch):
    row = job()
    db = session(monkeypatch, row)
    await guarded_commit(db, row.id, row.lease_token)
    assert not events(db)


@pytest.mark.parametrize("cancelled,lock_free", [(False, True), (True, True), (False, False)])
async def test_recovery_logs_only_durable_non_cancel_failure(monkeypatch, cancelled, lock_free):
    row = job(locked_at=worker._now() - timedelta(hours=1),
              cancel_requested_at=worker._now() if cancelled else None)
    db = session(monkeypatch, lock_free)
    db.scalars.return_value = [row]
    await worker._recover_interrupted_jobs()
    assert len(events(db)) == (1 if lock_free and not cancelled else 0)
    if events(db):
        assert events(db)[0].event_metadata["error_category"] == "interrupted"
        assert events(db)[0].event_metadata["reason"] == "lease_expired"
    db.commit.assert_awaited_once()


async def test_cancelled_finish_has_no_processing_outcome(monkeypatch):
    row = job(cancel_requested_at=worker._now())
    db = session(monkeypatch, row)
    await worker._finish(row.id, row.lease_token, RuntimeError("cancelled"))
    assert row.status == "cancelled" and not events(db)


async def test_exhaustion_audits_only_updated_rows(monkeypatch):
    row = job(status="failed", attempts=3)
    db = session(monkeypatch)
    db.execute.return_value.scalars.return_value = [row]
    monkeypatch.setattr(worker.settings, "process_only_job_id", "")
    assert await worker._claim_next() is None
    event, = events(db)
    assert event.event_metadata["error_category"] == "attempts_exhausted"
    assert event.event_metadata["previous_state"] == "pending"
    assert event.event_key.endswith(":exhausted")
    db.commit.assert_awaited_once()


async def test_direct_reprocess_failure_stages_before_commit(monkeypatch):
    row = job(source="manual_reprocess")
    db = session(monkeypatch, row)

    async def commit():
        event, = events(db)
        assert row.status == "failed" and row.lease_token is None
        assert event.event_metadata["error_category"] == "reprocess_conflict"
        assert "SECRET" not in str(event.event_metadata)

    db.commit.side_effect = commit
    with pytest.raises(steps.ReprocessConflict):
        await steps._stop_reprocess_conflict(db, row.id, row.lease_token, "SECRET")
    db.scalar.return_value = None
    await worker._finish(row.id, uuid4(), RuntimeError("conflict"))
    assert len(events(db)) == 1


async def test_commit_failure_propagates_without_separate_audit_commit(monkeypatch):
    row = job()
    db = session(monkeypatch, row)
    db.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError, match="commit failed"):
        await guarded_commit(db, row.id, row.lease_token, complete=True)
    assert len(events(db)) == 1  # Staged only; persistence belongs to this failed commit.
    db.commit.assert_awaited_once()
