"""Tests for app/graph/client.py — Graph API calls via respx mock."""
import pytest
import respx
import httpx
from datetime import datetime, timezone
from unittest.mock import patch

_BASE = "https://graph.microsoft.com/v1.0"


def _mock_token():
    return patch("app.graph.client.get_token", return_value="fake-token")


class TestListRecordingsFolder:
    @staticmethod
    def _root_path(drive_id: str) -> str:
        return f"{_BASE}/drives/{drive_id}/root:/Recordings:/children"

    @staticmethod
    def _documents_path(drive_id: str) -> str:
        return f"{_BASE}/drives/{drive_id}/root:/Documents/Recordings:/children"

    @staticmethod
    def _root_traversal(drive_id: str) -> str:
        return (
            f"{_BASE}/drives/{drive_id}/root/children"
            "?$select=id,name,folder,parentReference"
        )

    @respx.mock
    async def test_root_recordings_folder_returns_mp4_files_only(self):
        from app.graph.client import list_recordings_folder
        respx.get(self._root_path("drive-123")).mock(return_value=httpx.Response(200, json={
            "value": [
                {"id": "f1", "name": "meeting.mp4"},
                {"id": "f2", "name": "notes.docx"},
                {"id": "f3", "name": "recording2.mp4"},
            ]
        }))
        respx.get(self._documents_path("drive-123")).mock(return_value=httpx.Response(404))
        respx.get(self._root_traversal("drive-123")).mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        with _mock_token():
            result = await list_recordings_folder("drive-123")
        names = [r["name"] for r in result]
        assert "meeting.mp4" in names
        assert "notes.docx" not in names
        assert "recording2.mp4" in names

    @respx.mock
    async def test_finds_documents_recordings_folder(self):
        from app.graph.client import list_recordings_folder
        respx.get(self._root_path("drive-xyz")).mock(return_value=httpx.Response(404))
        respx.get(self._documents_path("drive-xyz")).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "f1", "name": "meeting.mp4"}]
        }))
        respx.get(self._root_traversal("drive-xyz")).mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        with _mock_token():
            result = await list_recordings_folder("drive-xyz")
        assert [item["name"] for item in result] == ["meeting.mp4"]

    @respx.mock
    async def test_finds_recordings_under_another_root_folder(self):
        from app.graph.client import list_recordings_folder
        parent_url = (
            f"{_BASE}/drives/drive-sub/items/client-files/children"
            "?$select=id,name,folder,parentReference"
        )
        children_url = f"{_BASE}/drives/drive-sub/items/nested-recordings/children"
        respx.get(self._root_path("drive-sub")).mock(return_value=httpx.Response(404))
        respx.get(self._documents_path("drive-sub")).mock(return_value=httpx.Response(404))
        respx.get(self._root_traversal("drive-sub")).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "client-files", "name": "Client Files", "folder": {}}]
        }))
        respx.get(parent_url).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "nested-recordings", "name": "Recordings", "folder": {}}]
        }))
        respx.get(children_url).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "nested-mp4", "name": "nested-meeting.mp4"}]
        }))
        with _mock_token():
            result = await list_recordings_folder("drive-sub")
        assert [item["id"] for item in result] == ["nested-mp4"]

    @respx.mock
    async def test_returns_empty_list_when_no_recordings_folder_exists(self):
        from app.graph.client import list_recordings_folder
        respx.get(self._root_path("drive-empty")).mock(return_value=httpx.Response(404))
        respx.get(self._documents_path("drive-empty")).mock(return_value=httpx.Response(404))
        respx.get(self._root_traversal("drive-empty")).mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        with _mock_token():
            result = await list_recordings_folder("drive-empty")
        assert result == []

    @respx.mock
    async def test_traversal_and_recording_listing_support_pagination(self):
        from app.graph.client import list_recordings_folder
        traversal_next_url = f"{_BASE}/drives/drive-paged/root/children-page-2"
        children_url = f"{_BASE}/drives/drive-paged/items/later-folder/children"
        children_next_url = f"{_BASE}/drives/drive-paged/items/later-folder/children-page-2"
        respx.get(self._root_path("drive-paged")).mock(return_value=httpx.Response(404))
        respx.get(self._documents_path("drive-paged")).mock(return_value=httpx.Response(404))
        respx.get(self._root_traversal("drive-paged")).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "near-match", "name": "Recordings archive", "file": {}}],
            "@odata.nextLink": traversal_next_url,
        }))
        respx.get(traversal_next_url).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "later-folder", "name": "Recordings", "folder": {}}]
        }))
        respx.get(children_url).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "first-mp4", "name": "first.mp4"}],
            "@odata.nextLink": children_next_url,
        }))
        respx.get(children_next_url).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "later-mp4", "name": "meeting.mp4"}]
        }))
        with _mock_token():
            result = await list_recordings_folder("drive-paged")
        assert [item["id"] for item in result] == ["first-mp4", "later-mp4"]

    @respx.mock
    async def test_traversal_stops_at_request_and_folder_boundaries(self, monkeypatch):
        from app.graph import client
        monkeypatch.setattr(client, "RECORDINGS_TRAVERSAL_MAX_REQUESTS", 1)
        monkeypatch.setattr(client, "RECORDINGS_TRAVERSAL_MAX_FOLDERS", 1)
        blocked_url = (
            f"{_BASE}/drives/drive-bounded/items/first-folder/children"
            "?$select=id,name,folder,parentReference"
        )
        respx.get(self._root_path("drive-bounded")).mock(return_value=httpx.Response(404))
        respx.get(self._documents_path("drive-bounded")).mock(return_value=httpx.Response(404))
        respx.get(self._root_traversal("drive-bounded")).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "first-folder", "name": "First Folder", "folder": {}}]
        }))
        blocked_route = respx.get(blocked_url).mock(return_value=httpx.Response(200, json={
            "value": [{"id": "too-deep", "name": "Recordings", "folder": {}}]
        }))
        with _mock_token():
            result = await client.list_recordings_folder("drive-bounded")
        assert result == []
        assert blocked_route.called is False


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


class TestGetUserPhoto:
    @respx.mock
    async def test_returns_photo_bytes_and_content_type(self, monkeypatch):
        from app.graph import client
        monkeypatch.setattr(client.settings, "graph_impl", "microsoft")
        upn = "alice@taxconsulting.co.za"
        respx.get(f"{_BASE}/users/{upn}/photo/$value").mock(
            return_value=httpx.Response(200, content=b"jpeg-data", headers={"content-type": "image/jpeg"})
        )
        with _mock_token():
            content, content_type = await client.get_user_photo(upn)
        assert content == b"jpeg-data"
        assert content_type == "image/jpeg"

    @respx.mock
    async def test_missing_photo_uses_specific_exception(self, monkeypatch):
        from app.graph import client
        monkeypatch.setattr(client.settings, "graph_impl", "microsoft")
        upn = "alice@taxconsulting.co.za"
        respx.get(f"{_BASE}/users/{upn}/photo/$value").mock(return_value=httpx.Response(404))
        with _mock_token(), pytest.raises(client.ProfilePhotoNotFound):
            await client.get_user_photo(upn)


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


class TestGetUpcomingCalendarEvents:
    @respx.mock
    async def test_queries_previous_seven_days_and_keeps_future_window(self, monkeypatch):
        from app.graph import client

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

        monkeypatch.setattr(client.settings, "graph_impl", "microsoft")
        monkeypatch.setattr(client, "datetime", FixedDateTime)
        upn = "demo.user@taxconsulting.co.za"
        route = respx.get(f"{_BASE}/users/{upn}/calendarView").mock(
            return_value=httpx.Response(200, json={"value": [
                {
                    "id": "stand-by",
                    "subject": "Stand by",
                    "start": {"dateTime": "2026-08-28T14:00:00Z", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-08-28T14:30:00Z", "timeZone": "UTC"},
                    "isOnlineMeeting": True,
                },
                {
                    "id": "future-meeting",
                    "subject": "Future meeting",
                    "start": {"dateTime": "2026-09-03T09:00:00Z", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-09-03T09:30:00Z", "timeZone": "UTC"},
                    "isOnlineMeeting": True,
                },
            ]})
        )

        with _mock_token():
            rows = await client.get_upcoming_calendar_events(upn, days=7)

        params = route.calls.last.request.url.params
        assert params["startDateTime"] == "2026-08-25T12:00:00Z"
        assert params["endDateTime"] == "2026-09-08T12:00:00Z"
        assert [row["id"] for row in rows] == ["stand-by", "future-meeting"]


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
