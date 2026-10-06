"""Recording actions stage attribution with their business transaction."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import recording_jobs, recordings
from app.models import AuditEvent, ProcessingState
from app.services import jobs


def actor():
    return SimpleNamespace(id=uuid4(), upn="admin@example.test", entra_oid="entra-admin",
                           is_admin=True, is_subscribed=True)


def job(status="processing"):
    return SimpleNamespace(id=uuid4(), status=status, owner_upn="owner@example.test",
                           drive_id="drive", drive_item_id="item", source="manual",
                           cancel_requested_at=None, lease_token=uuid4(), locked_at=None,
                           last_error=None)


def session(*rows):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=rows)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    return db


def events(db):
    return [call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditEvent)]


@pytest.mark.parametrize("discovered", [False, True])
async def test_import_audit_precedes_only_commit(monkeypatch, discovered):
    user = actor()
    db = session(user, object() if discovered else None, None)
    monkeypatch.setattr(recordings, "_verify_owned_drive_item", AsyncMock(return_value={}))
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(recordings, "enqueue_retry_job" if discovered else "enqueue_recording_job", enqueue)

    async def commit():
        assert len(events(db)) == 1
        event = events(db)[0]
        assert event.event_type == "recording.import" and event.outcome == "requested"
        assert event.actor_id == str(user.id) and event.actor_entra_oid == user.entra_oid
        assert event.job_id == enqueue.await_args.kwargs["job_id"]
        assert event.correlation_id == event.resource_id == event.job_id

    db.commit.side_effect = commit
    assert await recordings.import_recording(recordings.ImportRequest(
        drive_id="drive", drive_item_id="item"), db, user.upn) == {"ok": True, "queued": True}
    assert enqueue.await_args.kwargs["commit"] is False
    db.commit.assert_awaited_once()


async def test_import_duplicate_has_no_event_or_commit(monkeypatch):
    user = actor()
    db = session(user, None)
    monkeypatch.setattr(recordings, "_verify_owned_drive_item", AsyncMock(return_value={}))
    monkeypatch.setattr(recordings, "enqueue_recording_job", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as exc:
        await recordings.import_recording(recordings.ImportRequest(
            drive_id="drive", drive_item_id="item"), db, user.upn)
    assert exc.value.status_code == 409 and not events(db)
    db.commit.assert_not_awaited()


async def test_retry_attributes_admin_and_stages_before_commit(monkeypatch):
    user, old = actor(), job("failed")
    meeting = SimpleNamespace(id=uuid4(), state=ProcessingState.failed, error="old")
    db = session(old, meeting)
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(recording_jobs, "enqueue_retry_job", enqueue)

    async def commit():
        event, = events(db)
        assert event.event_type == "recording.retry" and event.outcome == "requested"
        assert event.actor_upn == user.upn != old.owner_upn
        assert event.event_metadata["parent_job_id"] == str(old.id)
        assert event.job_id == enqueue.await_args.kwargs["job_id"]
        assert meeting.state == ProcessingState.queued

    db.commit.side_effect = commit
    await recording_jobs.retry_job(old.id, db, user)
    assert enqueue.await_args.kwargs["commit"] is False
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("status", ["pending", "processing"])
async def test_cancel_logs_first_request_only(status):
    user, row = actor(), job(status)
    db = session(row, None, row) if status == "pending" else session(row, row)

    async def commit():
        event, = events(db)
        assert event.event_type == "recording.cancel" and event.outcome == "requested"
        assert event.actor_id == str(user.id)
        assert row.cancel_requested_at is not None

    db.commit.side_effect = commit
    await recording_jobs.cancel_job(row.id, db, user)
    await recording_jobs.cancel_job(row.id, db, user)
    assert len(events(db)) == 1


async def test_reprocess_commit_failure_does_not_return_success(monkeypatch):
    user, old = actor(), job("completed")
    meeting = SimpleNamespace(id=uuid4(), state=ProcessingState.awaiting_review,
                             organizer_upn=old.owner_upn, transcript="raw",
                             extracted_json={"raw_transcript": "raw"}, action_items=[])
    db = session(meeting, SimpleNamespace(drive_id="drive"))
    monkeypatch.setattr(recordings, "_verify_owned_drive_item", AsyncMock())
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(recordings, "enqueue_retry_job", enqueue)

    async def fail_commit():
        event, = events(db)
        assert event.event_type == "recording.reprocess" and event.outcome == "requested"
        assert event.actor_id == str(user.id)
        assert event.meeting_id == meeting.id
        assert event.event_metadata["parent_job_id"] == str(old.id)
        assert meeting.transcript == "raw" and meeting.state == ProcessingState.awaiting_review
        raise RuntimeError("transaction failed")

    db.commit.side_effect = fail_commit
    with pytest.raises(RuntimeError, match="transaction failed"):
        await recordings._queue_reprocess(db, "item", user, old)
    assert enqueue.await_args.kwargs["commit"] is False
    db.commit.assert_awaited_once()


async def test_retry_helper_caller_owned_transaction(monkeypatch):
    new_id = uuid4()
    db = session(None, new_id)
    assert await jobs.enqueue_retry_job(db, drive_item_id="item", drive_id="drive",
        owner_upn="owner@example.test", commit=False, job_id=new_id)
    assert db.scalar.await_args.args[0].compile().params["id"] == new_id
    db.commit.assert_not_awaited()


async def test_import_helper_caller_owned_transaction(monkeypatch):
    new_id = uuid4()
    db = session()
    monkeypatch.setattr(jobs, "claim_item", AsyncMock(return_value=True))
    assert await jobs.enqueue_recording_job(db, drive_item_id="item", drive_id="drive",
        owner_upn="owner@example.test", source="manual", commit=False, job_id=new_id)
    assert db.add.call_args.args[0].id == new_id
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


async def test_retry_enqueue_conflict_rolls_back_without_audit(monkeypatch):
    row = job("failed")
    db = session(row, None)
    monkeypatch.setattr(recording_jobs, "enqueue_retry_job", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as exc:
        await recording_jobs.retry_job(row.id, db, actor())
    assert exc.value.status_code == 409 and not events(db)
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


async def test_audit_validation_failure_prevents_business_commit(monkeypatch):
    row = job("failed")
    db = session(row, None)
    monkeypatch.setattr(recording_jobs, "enqueue_retry_job", AsyncMock(return_value=True))
    monkeypatch.setattr(recording_jobs, "add_audit_event", MagicMock(side_effect=ValueError("invalid audit")))
    with pytest.raises(ValueError, match="invalid audit"):
        await recording_jobs.retry_job(row.id, db, actor())
    db.commit.assert_not_awaited()
