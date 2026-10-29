"""Security and durability tests for manual recording processing."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


class TestRecordingOwnership:
    async def test_foreign_drive_is_rejected_before_item_lookup(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import recordings

        monkeypatch.setattr(
            recordings.graph,
            "get_user_drive_id",
            AsyncMock(return_value="signed-in-users-drive"),
        )
        get_item = AsyncMock()
        monkeypatch.setattr(recordings.graph, "get_drive_item", get_item)

        with pytest.raises(HTTPException) as exc:
            await recordings._verify_owned_drive_item(
                "user@taxconsulting.co.za", "somebody-elses-drive", "item-1"
            )

        assert exc.value.status_code == 403
        get_item.assert_not_awaited()

    async def test_owned_mp4_is_accepted(self, monkeypatch):
        from app.api import recordings

        monkeypatch.setattr(
            recordings.graph, "get_user_drive_id", AsyncMock(return_value="drive-1")
        )
        monkeypatch.setattr(
            recordings.graph,
            "get_drive_item",
            AsyncMock(return_value={"id": "item-1", "name": "Meeting.MP4"}),
        )

        item = await recordings._verify_owned_drive_item(
            "user@taxconsulting.co.za", "drive-1", "item-1"
        )
        assert item["id"] == "item-1"

    async def test_non_mp4_is_rejected(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import recordings

        monkeypatch.setattr(
            recordings.graph, "get_user_drive_id", AsyncMock(return_value="drive-1")
        )
        monkeypatch.setattr(
            recordings.graph,
            "get_drive_item",
            AsyncMock(return_value={"id": "item-1", "name": "secrets.pdf"}),
        )

        with pytest.raises(HTTPException) as exc:
            await recordings._verify_owned_drive_item(
                "user@taxconsulting.co.za", "drive-1", "item-1"
            )
        assert exc.value.status_code == 422


class TestRecordingQueue:
    async def test_new_recording_is_persisted(self, monkeypatch):
        from app.services import jobs

        db = AsyncMock()
        db.add = MagicMock()
        monkeypatch.setattr(jobs, "claim_item", AsyncMock(return_value=True))

        queued = await jobs.enqueue_recording_job(
            db,
            drive_item_id="item-1",
            drive_id="drive-1",
            owner_upn="owner@taxconsulting.co.za",
            source="manual",
        )

        assert queued is True
        db.add.assert_called_once()
        persisted = db.add.call_args.args[0]
        assert persisted.owner_upn == "owner@taxconsulting.co.za"
        await_args = jobs.claim_item.await_args
        assert await_args.kwargs["commit"] is False
        db.commit.assert_awaited_once()

    async def test_duplicate_recording_does_not_create_job(self, monkeypatch):
        from app.services import jobs

        db = AsyncMock()
        db.add = MagicMock()
        monkeypatch.setattr(jobs, "claim_item", AsyncMock(return_value=False))

        queued = await jobs.enqueue_recording_job(
            db,
            drive_item_id="item-1",
            drive_id="drive-1",
            owner_upn="owner@taxconsulting.co.za",
            source="manual",
        )

        assert queued is False
        db.add.assert_not_called()
        db.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "upn",
    ["revoked@taxconsulting.co.za", "pending@taxconsulting.co.za", "owner@taxconsulting.co.za"],
)
async def test_list_jobs_query_excludes_no_view_users_but_preserves_owner_path(upn):
    from sqlalchemy.dialects import postgresql
    from app.api import recording_jobs

    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [])
    user = SimpleNamespace(upn=upn, is_admin=False)

    assert await recording_jobs.list_jobs(db=db, user=user, limit=20) == []

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "meeting_participants.access_type" in sql
    assert "not in" in sql
    assert "recording_jobs.owner_upn" in sql
    assert "meetings.organizer_upn" in sql
    assert "meetings.transcript" not in sql
    assert "meetings.extracted_json" not in sql
    assert not any("Meeting.action_items" in str(option.path) for option in statement._with_options)


async def test_manual_import_queues_a_discovered_recording(monkeypatch):
    from app.api import recordings

    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[SimpleNamespace(id=uuid4(), upn="owner@example.com", entra_oid=None), MagicMock(), None])
    monkeypatch.setattr(
        recordings, "_verify_owned_drive_item",
        AsyncMock(return_value={"id": "item-1", "name": "test03.mp4"}),
    )
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(recordings, "enqueue_retry_job", enqueue)

    result = await recordings.import_recording(
        recordings.ImportRequest(drive_item_id="item-1", drive_id="drive-1"),
        db=db, upn="owner@example.com",
    )

    assert result == {"ok": True, "queued": True}
    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["commit"] is False
    assert enqueue.await_args.kwargs["source"] == "manual"
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("status", ["pending", "processing", "completed", "failed", "cancelled"])
@pytest.mark.parametrize("state", ["awaiting_review", "sent"])
async def test_status_projection_preserves_controls_and_conditional_loading(admin, status, state):
    from app.api.recording_jobs import list_jobs, job_out
    from app.models import ProcessingState
    from app.services.reprocessing import MANUAL_REPROCESS_SOURCE

    upn = "owner@example.test"
    meeting = SimpleNamespace(
        id=uuid4(), title="Meeting", state=ProcessingState(state),
        organizer_upn=upn, participants=[], transcript="words",
        extracted_json={"raw_transcript": "words"}, approved_by=None,
        approved_at=None, approved_recipients=None, email_delivery_status=None,
        action_items=[],
    )
    job = SimpleNamespace(
        id=uuid4(), drive_item_id="item", owner_upn=upn, status=status,
        source=MANUAL_REPROCESS_SOURCE, attempts=1, max_attempts=3,
        last_error=None, locked_at=None, cancel_requested_at=None,
    )
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [(job, meeting, None)])
    db.scalars.return_value = SimpleNamespace(all=lambda: [meeting])
    actual = await list_jobs(db=db, user=SimpleNamespace(upn=upn, is_admin=admin), limit=20)
    assert actual == [job_out(job, meeting, upn, admin)]
    needs_clean = state == "awaiting_review" and status in {"completed", "failed", "cancelled"}
    needs_organizer = state == "awaiting_review" and status == "completed" and not admin
    assert db.scalars.await_count == int(needs_clean) + int(needs_organizer)


@pytest.mark.parametrize("edited", [False, True])
async def test_status_clean_candidate_preserves_action_item_edit_check(edited):
    from app.api.recording_jobs import list_jobs
    from app.models import ProcessingState

    meeting = SimpleNamespace(
        id=uuid4(), title="Meeting", state=ProcessingState.awaiting_review,
        transcript="words", extracted_json={"raw_transcript": "words"},
        approved_by=None, approved_at=None, approved_recipients=None,
        email_delivery_status=None,
        action_items=[SimpleNamespace(edited_by="user" if edited else None, approved=False)],
    )
    job = SimpleNamespace(
        id=uuid4(), drive_item_id="item", owner_upn="owner", status="completed",
        source="manual", attempts=1, max_attempts=3, last_error=None,
        locked_at=None, cancel_requested_at=None,
    )
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [(job, meeting, None), (job, meeting, None)])
    db.scalars.return_value = SimpleNamespace(all=lambda: [meeting])
    result = await list_jobs(db=db, user=SimpleNamespace(upn="admin", is_admin=True), limit=20)
    assert all(row["can_reprocess"] is (not edited) for row in result)
    assert db.scalars.await_count == 1


async def test_status_unassociated_job_preserves_response_without_review_loading():
    from app.api.recording_jobs import list_jobs, job_out
    job = SimpleNamespace(
        id=uuid4(), drive_item_id="item", owner_upn="owner", status="pending",
        source="manual", attempts=0, max_attempts=3, last_error=None,
        locked_at=None, cancel_requested_at=None,
    )
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [(job, None, None)])
    result = await list_jobs(db=db, user=SimpleNamespace(upn="owner", is_admin=False), limit=20)
    assert result == [job_out(job, None, "owner", False)]
    db.scalars.assert_not_awaited()


async def test_status_nonorganizer_skips_large_review_fields():
    from app.api.recording_jobs import list_jobs, job_out
    from app.models import ProcessingState
    meeting = SimpleNamespace(
        id=uuid4(), title="Meeting", state=ProcessingState.awaiting_review,
        organizer_upn="someone_else", participants=[],
    )
    job = SimpleNamespace(
        id=uuid4(), drive_item_id="item", owner_upn="owner", status="completed",
        source="manual", attempts=1, max_attempts=3, last_error=None,
        locked_at=None, cancel_requested_at=None,
    )
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [(job, meeting, None), (job, meeting, None)])
    db.scalars.return_value = SimpleNamespace(all=lambda: [meeting])
    result = await list_jobs(db=db, user=SimpleNamespace(upn="owner", is_admin=False), limit=20)
    assert result == [job_out(job, meeting, "owner", False)]
    db.scalars.assert_awaited_once()
    from sqlalchemy.dialects import postgresql
    sql = str(db.scalars.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "meetings.transcript" not in sql
    assert "meetings.extracted_json" not in sql


async def test_two_queued_file_names_are_projected_by_exact_drive_and_item_without_old_title():
    from app.api.recording_jobs import list_jobs
    from app.models import ProcessingState
    from sqlalchemy.dialects import postgresql
    def job(item):
        return SimpleNamespace(id=uuid4(), drive_item_id=item, drive_id="drive-1", owner_upn="owner",
            status="pending", source="manual", attempts=0, max_attempts=3,
            last_error=None, locked_at=None, cancel_requested_at=None)
    old_meeting = SimpleNamespace(id=uuid4(), title="Trust IT3(t)", state=ProcessingState.awaiting_review)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [
        (job("oct22"), None, "October22.mp4"),
        (job("sept1"), old_meeting, "September1.mp4"),
        (job("unverified"), old_meeting, None),
    ])
    result = await list_jobs(db=db, user=SimpleNamespace(upn="owner", is_admin=False), limit=20)
    assert [r["title"] for r in result] == ["October22.mp4", "September1.mp4", "Recording identity unverified"]
    assert [r["drive_item_id"] for r in result] == ["oct22", "sept1", "unverified"]
    assert all(r["processing_status"] == "queued" and r["can_cancel"] for r in result)
    assert result[1]["meeting_id"] == str(old_meeting.id)
    assert result[2]["recording_identity_verified"] is False
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "processed_items.drive_item_id = recording_jobs.drive_item_id" in sql
    assert "processed_items.drive_id = recording_jobs.drive_id" in sql
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("ledger_drive,filename,expected", [
    ("drive-1", "Exact-file.mp4", "Exact-file.mp4"),
    ("different-drive", "Wrong-file.mp4", "Recording identity unverified"),
    ("drive-1", "  ", "Recording identity unverified"),
    (None, "Unscoped-file.mp4", "Recording identity unverified"),
])
async def test_status_filename_join_against_isolated_sqlite(ledger_drive, filename, expected):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import ProcessedItem, Meeting, MeetingParticipant, RecordingJob, ProcessingState
    from app.api.recording_jobs import list_jobs
    engine = create_engine("sqlite://")
    for model in (ProcessedItem, Meeting, MeetingParticipant, RecordingJob):
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add(ProcessedItem(drive_item_id="exact-item", drive_id=ledger_drive, filename=filename, source="local"))
        session.add(Meeting(drive_item_id="exact-item", title="Trust IT3(t)", organizer_upn="owner", state=ProcessingState.awaiting_review))
        session.add(RecordingJob(drive_item_id="exact-item", drive_id="drive-1", owner_upn="owner", status="pending", source="manual"))
        session.commit()
        db = AsyncMock()
        db.execute.side_effect = session.execute
        result = await list_jobs(db=db, user=SimpleNamespace(upn="owner", is_admin=False), limit=20)
        assert len(result) == 1
        assert result[0]["title"] == expected
        assert result[0]["recording_identity_verified"] is (expected == "Exact-file.mp4")
        assert result[0]["can_cancel"] is True
        db.commit.assert_not_awaited()
    engine.dispose()
