import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api import recording_jobs as api
from app.models import ProcessingState
from app.services.job_control import guarded_commit, JobCancelled, public_job_error
from app.queue import worker


def row(**overrides):
    data = dict(id=uuid4(), status="pending", drive_item_id="item", drive_id="drive",
                owner_upn="owner@example.test", cancel_requested_at=None, lease_token=uuid4(),
                locked_at=datetime.now(timezone.utc), last_error=None, attempts=1, max_attempts=3)
    data.update(overrides)
    return SimpleNamespace(**data)


def db_for(job, meeting=None):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[job, meeting])
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.parametrize("status,processing_status", [("pending", "queued"), ("processing", "processing"),
    ("failed", "failed"), ("completed", "completed"), ("cancelled", "cancelled")])
def test_job_api_status_mapping(status, processing_status):
    out = api.job_out(row(status=status), None, "owner@example.test")
    assert out["processing_status"] == processing_status
    assert out["phase"] == processing_status
    assert out["review_status"] is None


@pytest.mark.parametrize("processing_status", [ProcessingState.downloading, ProcessingState.transcribing,
    ProcessingState.extracting])
def test_real_pipeline_processing_status_mapping(processing_status):
    meeting = SimpleNamespace(id=uuid4(), title="Meeting", state=processing_status)
    out = api.job_out(row(status="processing"), meeting, "owner@example.test")
    assert out["processing_status"] == processing_status.value
    assert out["review_status"] is None


@pytest.mark.parametrize("review_status", [ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent])
def test_completed_processing_keeps_review_status_separate(review_status):
    meeting = SimpleNamespace(id=uuid4(), title="Meeting", state=review_status)
    out = api.job_out(row(status="completed"), meeting, "owner@example.test")
    assert out["processing_status"] == "completed"
    assert out["phase"] == "completed"
    assert out["review_status"] == review_status.value


def test_cancel_requested_is_not_cancelled():
    out = api.job_out(row(status="processing", cancel_requested_at=datetime.now(timezone.utc)), None, "owner@example.test")
    assert out["processing_status"] == "cancel_requested" and not out["can_cancel"]


@pytest.mark.parametrize("method", [api.cancel_job, api.retry_job])
async def test_other_attendee_cannot_control_recording(method):
    job = row(status="failed")
    with pytest.raises(HTTPException) as exc:
        await method(job.id, db_for(job), "attendee@example.test")
    assert exc.value.status_code == 403


async def test_cancel_queued_keeps_transcript_and_marks_cancelled():
    job = row()
    meeting = SimpleNamespace(state=ProcessingState.queued, transcript="saved raw", extracted_json={"original": "kept"})
    db = db_for(job, meeting)
    result = await api.cancel_job(job.id, db, job.owner_upn)
    assert result["status"] == "cancelled" and job.status == "cancelled"
    assert meeting.state == ProcessingState.cancelled and meeting.transcript == "saved raw"
    db.commit.assert_awaited_once()


async def test_running_cancel_requests_stop_without_claiming_completion():
    job = row(status="processing")
    token = job.lease_token
    db = db_for(job)
    result = await api.cancel_job(job.id, db, job.owner_upn)
    assert result["status"] == "cancel_requested"
    assert job.status == "processing" and job.lease_token == token and job.cancel_requested_at


@pytest.mark.parametrize("status", ["failed", "completed"])
async def test_terminal_job_cancel_rejected(status):
    job = row(status=status)
    with pytest.raises(HTTPException) as exc:
        await api.cancel_job(job.id, db_for(job), job.owner_upn)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("queued", [True, False])
async def test_retry_reuses_trusted_queue_ids_preserves_transcript_and_handles_dedup(monkeypatch, queued):
    job = row(status="failed")
    meeting = SimpleNamespace(state=ProcessingState.failed, transcript="original raw", extracted_json={"kept": True})
    db = db_for(job, meeting)
    enqueue = AsyncMock(return_value=queued)
    monkeypatch.setattr(api, "enqueue_retry_job", enqueue)
    if queued:
        assert (await api.retry_job(job.id, db, job.owner_upn))["status"] == "queued"
    else:
        with pytest.raises(HTTPException) as exc:
            await api.retry_job(job.id, db, job.owner_upn)
        assert exc.value.status_code == 409
        db.rollback.assert_awaited_once()
    assert meeting.transcript == "original raw" and meeting.extracted_json == {"kept": True}
    assert enqueue.call_args.kwargs["drive_id"] == "drive"


async def test_cancellation_fence_prevents_result_commit():
    db = db_for(None)
    with pytest.raises(JobCancelled):
        await guarded_commit(db, uuid4(), uuid4(), complete=True)
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()
    sql = str(db.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "cancel_requested_at IS NULL" in sql


async def test_result_commit_completes_job_atomically():
    job = row(status="processing")
    db = db_for(job)
    await guarded_commit(db, job.id, job.lease_token, complete=True)
    assert job.status == "completed" and job.lease_token is None
    db.commit.assert_awaited_once()


def test_errors_never_echo_secrets_or_internal_urls():
    error = "429 from https://db.example/?api_key=MY_SECRET token=ACCESS_TOKEN"
    out = public_job_error(error)
    assert "MY_SECRET" not in out and "ACCESS_TOKEN" not in out and "https" not in out
    assert "public" not in public_job_error("postgresql://user:password@private")


async def test_disabled_staging_worker_connects_but_never_claims(monkeypatch):
    stop = asyncio.Event()
    db = db_for(None)
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    monkeypatch.setattr(worker.settings, "recording_processing_enabled", False)
    monkeypatch.setattr(worker, "_recover_interrupted_jobs", AsyncMock())
    claim = AsyncMock()
    monkeypatch.setattr(worker, "_claim_next", claim)
    monkeypatch.setattr(worker, "_idle", AsyncMock(side_effect=lambda _: stop.set()))
    await worker.run_worker(stop)
    db.execute.assert_awaited_once()
    claim.assert_not_awaited()
