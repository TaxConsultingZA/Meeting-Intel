"""Synthetic-only monitoring evidence; no provider or production DB access."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api.admin import router
from app.db import get_db
from app.models import AuditEvent
from app.services.audit import add_audit_event
from app.services.processing_monitor import project_job, query_processing_monitor
from app.services import transcription_submission as submission
from app.ai.audit_usage import capture_usage, reported_usage

NOW = datetime.now(timezone.utc)


def job(**changes):
    values = dict(id=uuid4(), status="failed", attempts=2, created_at=NOW,
                  provider_transcript_id=None, provider_status="submission_unknown",
                  audio_duration_seconds=None, last_error="token=SECRET transcript=PRIVATE")
    values.update(changes)
    return SimpleNamespace(**values)


def event(kind, *, attempt=2, offset=0, metadata=None):
    return SimpleNamespace(id=uuid4(), event_key=kind, event_type=kind,
        outcome="succeeded", occurred_at=NOW+timedelta(seconds=offset),
        event_metadata=metadata or {"attempt": attempt, "new_state": "failed"})


def test_unknown_is_not_zero_or_attempts_and_no_sensitive_error():
    result = project_job(job(), [])
    assert result["confirmed_submissions"] is None
    assert result["processing_duration_seconds"] is None
    assert result["audio_duration_seconds"] is None
    assert result["failure"] is None
    assert result["actual_cost"] is result["estimated_cost"] is None
    assert result["token_usage"] == []
    assert "SECRET" not in str(result) and "PRIVATE" not in str(result)


def test_duplicate_reads_do_not_accumulate_and_duration_uses_matching_attempt():
    accepted = event("provider.submitted")
    usage = event("ai.extraction_completed", metadata={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "key": "SECRET"})
    events = [accepted, accepted, usage, usage, event("recording.started"), event("recording.processing", offset=10)]
    result = project_job(job(), events)
    assert result == project_job(job(id=result["job_id"]), events)
    assert result["confirmed_submissions"] == 1
    assert result["ai_submissions_with_reported_usage"] == 1
    assert len(result["token_usage"]) == 1
    assert result["token_usage"][0]["total_tokens"] == 5
    assert result["processing_duration_seconds"] == 10
    assert "SECRET" not in str(result)
    assert project_job(job(attempts=3), events)["processing_duration_seconds"] is None


def test_legacy_acceptance_and_audio_are_evidence_but_reservation_is_not():
    result = project_job(job(provider_transcript_id="PRIVATE", provider_status="completed", audio_duration_seconds=18), [])
    assert result["confirmed_submissions"] == 1 and result["audio_duration_seconds"] == 18
    assert result["submission_evidence"] == "persisted_provider_id"
    assert "PRIVATE" not in str(result)
    assert project_job(job(), [event("provider.reserved")])["confirmed_submissions"] is None


async def test_filters_are_parameterized_and_event_window_is_not_truncated():
    db = MagicMock()
    row = job()
    db.scalars = AsyncMock(side_effect=[MagicMock(all=lambda: [row]), MagicMock(all=lambda: [])])
    await query_processing_monitor(db, job_id=row.id, recording_id="synthetic-item", status="failed")
    first, second = [str(c.args[0]) for c in db.scalars.await_args_list]
    assert "recording_jobs.drive_item_id =" in first and "recording_jobs.status =" in first
    assert "LIMIT" in first and "created_at" in first
    assert "audit_events.job_id IN" in second and "occurred_at >=" not in second
    with pytest.raises(ValueError):
        await query_processing_monitor(db, start=NOW, end=NOW-timedelta(days=1))


@pytest.mark.parametrize("admin,code", [(True, 200), (False, 403), (None, 403)])
def test_api_roles_and_no_store(admin, code):
    db = MagicMock(scalar=AsyncMock(return_value=SimpleNamespace(is_admin=admin) if admin is not None else None),
                   scalars=AsyncMock(return_value=MagicMock(all=lambda: [])))
    app = FastAPI(); app.include_router(router)
    async def session():
        yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        result = client.get("/admin/processing-monitor", headers={"Authorization": "Bearer mock:admin@taxconsulting.co.za"})
        assert result.status_code == code
        if code == 200:
            assert result.headers["cache-control"] == "no-store"
        else:
            db.scalars.assert_not_awaited()
        assert client.get("/admin/processing-monitor").status_code == 401


async def test_checkpoint_deduplicates_under_existing_job_lock(monkeypatch):
    row = job(submission_count=1)
    db = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db); db.__aexit__ = AsyncMock(return_value=False)
    db.scalar = AsyncMock(side_effect=[row, None, row, uuid4()])
    db.commit = AsyncMock()
    monkeypatch.setattr(submission, "SessionLocal", lambda: db)
    for _ in range(2):
        await submission.checkpoint(row.id, uuid4(), provider_status="submitted", provider_transcript_id="PRIVATE")
    assert db.add.call_count == 1
    audit = db.add.call_args.args[0]
    assert audit.event_type == "provider.submitted" and "PRIVATE" not in str(audit.event_metadata)
    assert "FOR UPDATE" in str(db.scalar.call_args_list[0].args[0])


def test_existing_unique_event_constraint_in_isolated_sqlite():
    engine = create_engine("sqlite://")
    AuditEvent.__table__.create(engine)
    identity = uuid4()
    with Session(engine) as db:
        kwargs = dict(event_type="provider.submitted", outcome="succeeded", actor_type="system", actor_id="recording_worker",
                      resource_type="recording_job", resource_id=identity, job_id=identity,
                      correlation_id=identity, event_key=f"provider.submitted:{identity}")
        add_audit_event(db, **kwargs); db.commit()
        add_audit_event(db, **kwargs)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.query(AuditEvent).count() == 1
    engine.dispose()


def test_usage_capture_is_task_local_and_typed():
    first = {}; token = reported_usage.set(first)
    try:
        capture_usage({"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2})
        assert first == {}
        capture_usage({"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "secret": "SECRET"})
        assert first == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    finally:
        reported_usage.reset(token)
    assert reported_usage.get() is None
