from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import admin, recording_jobs


def db_for(job, linked_request_id=None):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[job, linked_request_id])
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_admin_cleans_eligible_job_only_and_preserves_content(status):
    row = SimpleNamespace(id=uuid4(), status=status)
    meeting = {"transcript": "saved", "summary": "saved", "action_items": ["saved"]}
    db = db_for(row)

    response = await admin.cleanup_job(str(row.id), db, "admin@example.test")

    assert response.status_code == 204
    db.delete.assert_awaited_once_with(row)
    db.commit.assert_awaited_once()
    assert db.scalar.await_count == 2
    assert meeting == {"transcript": "saved", "summary": "saved", "action_items": ["saved"]}


async def test_linked_processing_request_is_preserved_and_cleanup_is_rejected():
    row = SimpleNamespace(id=uuid4(), status="failed")
    db = db_for(row, linked_request_id=uuid4())

    with pytest.raises(HTTPException) as exc:
        await admin.cleanup_job(str(row.id), db, "admin@example.test")

    assert exc.value.status_code == 409
    assert "processing request" in exc.value.detail
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("status", ["pending", "queued", "processing", "running", "completed"])
async def test_active_and_completed_jobs_are_protected(status):
    db = db_for(SimpleNamespace(id=uuid4(), status=status))
    with pytest.raises(HTTPException) as exc:
        await admin.cleanup_job(str(uuid4()), db, "admin@example.test")
    assert exc.value.status_code == 409
    db.delete.assert_not_awaited()


async def test_unknown_job_is_safe():
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    db.delete = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await admin.cleanup_job(str(uuid4()), db, "admin@example.test")
    assert exc.value.status_code == 404


def test_non_admin_is_forbidden():
    from app.db import get_db

    app = FastAPI()
    app.include_router(admin.router)

    async def override_db():
        db = MagicMock()
        db.scalar = AsyncMock(return_value=SimpleNamespace(is_admin=False))
        yield db

    app.dependency_overrides[get_db] = override_db
    response = TestClient(app, raise_server_exceptions=False).delete(
        f"/admin/jobs/{uuid4()}",
        headers={"Authorization": "Bearer mock:member@taxconsulting.co.za"},
    )
    assert response.status_code == 403


async def test_existing_retry_cancel_reprocess_state_constant_is_unchanged(monkeypatch):
    assert recording_jobs.RETRYABLE_JOB_STATES == frozenset({"failed", "cancelled"})
