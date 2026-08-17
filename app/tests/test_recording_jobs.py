"""Security and durability tests for manual recording processing."""
from unittest.mock import AsyncMock, MagicMock

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
