from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.api import admin as admin_api, recording_jobs, recording_processing_requests, recordings
from app.models import ProcessingState
from app.schemas import AdminRevokeAccessIn


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
                              transcript="must not leak", summary="must not leak", participants=[
                                  SimpleNamespace(user_upn="owner@example.test", is_organizer=True,
                                                  access_type="participant", edit_access_status="none"),
                                  SimpleNamespace(user_upn="editor@example.test", is_organizer=False,
                                                  access_type="shared", edit_access_status="approved"),
                              ])
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
    assert rows[0]["access"][1]["view_access"] and rows[0]["access"][1]["edit_access"]
    assert "transcript" not in rows[0] and "summary" not in rows[0]


async def test_admin_revokes_edit_access_with_existing_audit_fields():
    participant = SimpleNamespace(user_upn="editor@example.test", is_organizer=False,
                                  access_type="historical", edit_access_status="approved",
                                  edit_decided_at=None, edit_decided_by=None)
    meeting = SimpleNamespace(id=uuid4(), organizer_upn="owner@example.test", participants=[participant])
    db = db_with_scalars(meeting)

    result = await admin_api.revoke_meeting_access(
        str(meeting.id), participant.user_upn, AdminRevokeAccessIn(access_type="edit"),
        db, "admin@example.test",
    )

    assert result["status"] == "revoked"
    assert participant.access_type == "historical"
    assert participant.edit_access_status == "denied"
    assert participant.edit_decided_by == "admin@example.test"
    assert participant.edit_decided_at is not None


async def test_admin_revokes_view_without_deleting_participant_or_meeting_data():
    participant = SimpleNamespace(user_upn="viewer@example.test", is_organizer=False,
                                  access_type="shared", edit_access_status="none",
                                  edit_decided_at=None, edit_decided_by=None)
    meeting = SimpleNamespace(id=uuid4(), organizer_upn="owner@example.test", participants=[participant])
    db = db_with_scalars(meeting)

    await admin_api.revoke_meeting_access(
        str(meeting.id), participant.user_upn, AdminRevokeAccessIn(access_type="view"),
        db, "admin@example.test",
    )

    assert participant.access_type == "revoked"
    assert participant.edit_access_status == "denied"
    assert participant.edit_decided_by == "admin@example.test"
    db.delete.assert_not_called()


async def test_admin_access_request_feed_unifies_processing_view_and_edit_requests():
    now = datetime.now(timezone.utc)
    requester_id, owner_id = uuid4(), uuid4()
    processing = SimpleNamespace(
        id=uuid4(), meeting_id=None, requester_user_id=requester_id,
        recording_owner_user_id=owner_id, event_snapshot={"subject": "Processing meeting"},
        drive_item_id="processing-item", status="pending", created_at=now,
    )
    view_meeting = SimpleNamespace(title="View meeting", organizer_upn="owner@example.test")
    view_request = SimpleNamespace(
        id=uuid4(), meeting_id=uuid4(), meeting=view_meeting, user_upn="viewer@example.test",
        access_type="request_view", edit_access_status="pending", edit_requested_at=now,
        edit_decided_at=None,
    )
    edit_meeting = SimpleNamespace(title="Edit meeting", organizer_upn="owner@example.test")
    edit_request = SimpleNamespace(
        id=uuid4(), meeting_id=uuid4(), meeting=edit_meeting, user_upn="editor@example.test",
        access_type="participant", edit_access_status="approved", edit_requested_at=now,
        edit_decided_at=now,
    )
    requester = SimpleNamespace(id=requester_id, upn="requester@example.test", display_name="Requester")
    owner = SimpleNamespace(id=owner_id, upn="owner@example.test", display_name="Owner")

    def scalar_result(values):
        result = MagicMock()
        result.all.return_value = values
        return result

    db = MagicMock()
    db.scalars = AsyncMock(side_effect=[
        scalar_result([processing]), scalar_result([view_request, edit_request]),
        scalar_result([requester, owner]), scalar_result([]), scalar_result([]),
    ])

    rows = await admin_api.list_access_requests(db, "admin@example.test")

    assert {row["request_type"] for row in rows} == {"processing", "view", "edit"}
    assert all({"meeting", "requester_upn", "owner_upn", "status"} <= row.keys() for row in rows)
    assert next(row for row in rows if row["request_type"] == "processing")["can_approve"] is True
