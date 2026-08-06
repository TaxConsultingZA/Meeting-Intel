"""Tests for app/graph/client.py — Graph API calls via respx mock."""
import pytest
import respx
import httpx
from unittest.mock import patch

_BASE = "https://graph.microsoft.com/v1.0"


def _mock_token():
    return patch("app.graph.client.get_token", return_value="fake-token")


class TestListRecordingsFolder:
    @respx.mock
    async def test_returns_mp4_files_only(self):
        from app.graph.client import list_recordings_folder
        url = f"{_BASE}/drives/drive-123/root:/Recordings:/children"
        respx.get(url).mock(return_value=httpx.Response(200, json={
            "value": [
                {"id": "f1", "name": "meeting.mp4"},
                {"id": "f2", "name": "notes.docx"},
                {"id": "f3", "name": "recording2.mp4"},
            ]
        }))
        with _mock_token():
            result = await list_recordings_folder("drive-123")
        names = [r["name"] for r in result]
        assert "meeting.mp4" in names
        assert "notes.docx" not in names
        assert "recording2.mp4" in names

    @respx.mock
    async def test_returns_empty_list_on_404(self):
        from app.graph.client import list_recordings_folder
        url = f"{_BASE}/drives/drive-xyz/root:/Recordings:/children"
        respx.get(url).mock(return_value=httpx.Response(404))
        with _mock_token():
            result = await list_recordings_folder("drive-xyz")
        assert result == []


class TestGetUserDriveId:
    @respx.mock
    async def test_returns_drive_id(self):
        from app.graph.client import get_user_drive_id
        upn = "alice@taxconsulting.co.za"
        respx.get(f"{_BASE}/users/{upn}/drive").mock(
            return_value=httpx.Response(200, json={"id": "drive-abc"})
        )
        with _mock_token():
            result = await get_user_drive_id(upn)
        assert result == "drive-abc"

    @respx.mock
    async def test_raises_on_403(self):
        from app.graph.client import get_user_drive_id
        upn = "noaccess@taxconsulting.co.za"
        respx.get(f"{_BASE}/users/{upn}/drive").mock(
            return_value=httpx.Response(403, json={"error": {"message": "Forbidden"}})
        )
        with _mock_token(), pytest.raises(httpx.HTTPStatusError):
            await get_user_drive_id(upn)


class TestGetEventAttendees:
    @respx.mock
    async def test_parses_semicolon_separated_attendees(self):
        from app.graph.client import get_event_attendees
        url = f"{_BASE}/drives/drive-1/items/item-1/listItem"
        respx.get(url).mock(return_value=httpx.Response(200, json={
            "fields": {"Attendees": "alice@x.com;bob@x.com;carol@x.com"}
        }))
        with _mock_token():
            result = await get_event_attendees("drive-1", "item-1")
        assert "alice@x.com" in result
        assert "bob@x.com" in result

    @respx.mock
    async def test_returns_empty_list_on_non_200(self):
        from app.graph.client import get_event_attendees
        url = f"{_BASE}/drives/drive-1/items/item-1/listItem"
        respx.get(url).mock(return_value=httpx.Response(403))
        with _mock_token():
            result = await get_event_attendees("drive-1", "item-1")
        assert result == []

    @respx.mock
    async def test_filters_out_non_email_entries(self):
        from app.graph.client import get_event_attendees
        url = f"{_BASE}/drives/drive-1/items/item-1/listItem"
        respx.get(url).mock(return_value=httpx.Response(200, json={
            "fields": {"Attendees": "alice@x.com;notanemail;bob@x.com"}
        }))
        with _mock_token():
            result = await get_event_attendees("drive-1", "item-1")
        assert "notanemail" not in result
        assert len(result) == 2


class TestLocalMockGraph:
    async def test_mock_drives_and_recordings_are_isolated_per_user(self, monkeypatch):
        from app.graph import client
        monkeypatch.setattr(client.settings, "graph_impl", "mock")

        alice_drive = await client.get_user_drive_id("alice@taxconsulting.co.za")
        bob_drive = await client.get_user_drive_id("bob@taxconsulting.co.za")
        alice_items = await client.list_recordings_folder(alice_drive)
        bob_items = await client.list_recordings_folder(bob_drive)

        assert alice_drive != bob_drive
        assert alice_items[0]["id"] != bob_items[0]["id"]

    async def test_mock_recording_belongs_to_current_drive_owner(self, monkeypatch):
        from app.graph import client
        monkeypatch.setattr(client.settings, "graph_impl", "mock")

        drive = await client.get_user_drive_id("alice@taxconsulting.co.za")
        metadata = await client.get_drive_item(drive, "mock-item")
        attendees = await client.get_event_attendees(drive, "mock-item")

        assert metadata["createdBy"]["user"]["email"] == "alice@taxconsulting.co.za"
        assert "alice@taxconsulting.co.za" in attendees

    async def test_returns_demo_recording_without_http(self, monkeypatch):
        from app.graph import client
        monkeypatch.setattr(client.settings, "graph_impl", "mock")

        rows = await client.list_recordings_folder("mock-drive::demo.user@taxconsulting.co.za")

        assert len(rows) == 1
        assert rows[0]["id"] == "mock-drive::demo.user@taxconsulting.co.za::recording-past-untranscribed"
        assert "Untranscribed" in rows[0]["name"]
        assert rows[0]["name"].endswith(".mp4")

    async def test_download_creates_local_marker_file(self, monkeypatch, tmp_path):
        from app.graph import client
        monkeypatch.setattr(client.settings, "graph_impl", "mock")
        destination = tmp_path / "recording.mp4"

        await client.download_drive_item("mock-drive", "mock-item", str(destination))

        assert destination.read_bytes() == b"MEETING_INTEL_LOCAL_MOCK_RECORDING"

    async def test_mock_calendar_is_future_teams_meeting(self, monkeypatch):
        from app.graph import client
        monkeypatch.setattr(client.settings, "graph_impl", "mock")

        rows = await client.get_upcoming_calendar_events("demo.user@taxconsulting.co.za")

        assert rows[0]["isOnlineMeeting"] is True
        assert rows[0]["subject"] == "Quarterly Planning (Mock)"

    async def test_mock_send_mail_is_noop(self, monkeypatch):
        from app.graph import client
        monkeypatch.setattr(client.settings, "graph_impl", "mock")

        result = await client.send_mail(
            "sender@taxconsulting.co.za",
            ["recipient@taxconsulting.co.za"],
            "Mock subject",
            "<p>Mock body</p>",
        )

        assert result is None
