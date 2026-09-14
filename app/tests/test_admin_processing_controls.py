from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.api import admin as admin_api, recording_jobs, recording_processing_requests, recordings
from app.models import ProcessingState


def actor(*, admin: bool):
    return SimpleNamespace(id=uuid4(), upn="admin@example.test" if admin else "member@example.test",
                           is_admin=admin, is_subscribed=False)


def job(status="pending"):
    return SimpleNamespace(id=uuid4(), status=status, drive_item_id="item", drive_id="owner-drive",
                           owner_upn="owner@example.test", cancel_requested_at=None, lease_token=uuid4(),
                           locked_at=datetime.now(timezone.utc), last_error=None, attempts=1,
                           max_attempts=3, source="manual")


def db_with_scalars(*values):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=values)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.parametrize("operation,status", [("cancel", "pending"), ("retry", "failed")])
async def test_admin_can_control_another_users_job(monkeypatch, operation, status):
    row = job(status)
    db = db_with_scalars(row, None)
    if operation == "retry":
        monkeypatch.setattr(recording_jobs, "enqueue_retry_job", AsyncMock(return_value=True))
        result = await recording_jobs.retry_job(row.id, db, actor(admin=True))
        assert result["status"] == "queued"
    else:
        result = await recording_jobs.cancel_job(row.id, db, actor(admin=True))
        assert result["status"] == "cancelled"


def test_admin_job_projection_exposes_controls_but_member_projection_does_not():
    row = job("failed")
    assert recording_jobs.job_out(row, None, "admin@example.test", is_admin=True)["can_retry"]
    assert not recording_jobs.job_out(row, None, "member@example.test")["can_retry"]


@pytest.mark.parametrize("admin,has_user_filter", [(True, False), (False, True)])
async def test_processing_request_scope_is_all_users_only_for_admin(admin, has_user_filter):
    db = db_with_scalars()
    result = MagicMock()
    result.__iter__.return_value = iter([])
    db.execute.return_value = result
    await recording_processing_requests.listing(db, actor(admin=admin))
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert ("requester_user_id =" in sql) is has_user_filter


async def test_admin_reprocesses_for_owner_through_existing_safe_workflow(monkeypatch):
    source = job("completed")
    meeting = SimpleNamespace(
        id=uuid4(), drive_item_id="item", organizer_upn="owner@example.test",
        state=ProcessingState.awaiting_review, transcript="raw", summary="summary",
        extracted_json={"raw_transcript": "raw"}, action_items=[], participants=[],
    )
    ledger = SimpleNamespace(drive_id="owner-drive")
    db = db_with_scalars(source, meeting, ledger)
    verify = AsyncMock()
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(recordings, "_verify_owned_drive_item", verify)
    monkeypatch.setattr(recordings, "enqueue_retry_job", enqueue)

    result = await recordings.reprocess_recording_job(source.id, db, actor(admin=True))

    assert result == {"ok": True, "queued": True}
    verify.assert_awaited_once_with("owner@example.test", "owner-drive", "item")
    assert enqueue.await_args.kwargs["owner_upn"] == "owner@example.test"


async def test_admin_meeting_inventory_contains_only_operational_metadata():
    meeting = SimpleNamespace(id=uuid4(), drive_item_id="item", title="Private meeting",
                              recorded_at=None, organizer_upn="owner@example.test",
                              state=ProcessingState.awaiting_review, created_at=datetime.now(timezone.utc),
                              transcript="must not leak", summary="must not leak")
    current_job = job("failed")
    request = SimpleNamespace(meeting_id=meeting.id, drive_item_id="item", status="approved",
                              created_at=datetime.now(timezone.utc))

    def scalar_result(values):
        result = MagicMock()
        result.all.return_value = values
        result.__iter__.return_value = iter(values)
        return result

    db = MagicMock()
    db.scalars = AsyncMock(side_effect=[
        scalar_result([meeting]), scalar_result([current_job]), scalar_result([request]),
        scalar_result(["item"]),
    ])

    rows = await admin_api.list_operational_meetings(db, "admin@example.test")

    assert rows[0]["owner_upn"] == "owner@example.test"
    assert rows[0]["job_status"] == "failed" and rows[0]["request_status"] == "approved"
    assert rows[0]["recording_status"] == "tracked"
    assert "transcript" not in rows[0] and "summary" not in rows[0]
