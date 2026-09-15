from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


@pytest.mark.asyncio
async def test_empty_upcoming_uses_persisted_data_without_graph(monkeypatch):
    from app.api import calendar
    from app.graph import client as graph

    db = AsyncMock()
    db.scalars.return_value = ScalarRows([])
    graph_scan = AsyncMock()
    monkeypatch.setattr(graph, "get_upcoming_calendar_events", graph_scan)

    assert await calendar.upcoming_meetings(days=7, db=db, upn="user@example.com") == []
    graph_scan.assert_not_awaited()
    sql = str(db.scalars.await_args.args[0])
    assert "synced_calendar_events.starts_at >" in sql


@pytest.mark.asyncio
async def test_recent_states_batches_queries_for_multiple_events():
    from app.services.cross_user_recordings import recent_states

    db = AsyncMock()
    db.scalars.side_effect = [ScalarRows([]), ScalarRows([])]
    requester = SimpleNamespace(id="user-id", upn="user@example.com")
    now = datetime.now(timezone.utc)
    events = [{
        "id": f"event-{index}",
        "iCalUId": f"ical-{index}",
        "subject": f"Meeting {index}",
        "start": {"dateTime": (now - timedelta(hours=2)).isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now - timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
        "organizer": {"emailAddress": {"address": "user@example.com"}},
    } for index in range(4)]

    states = await recent_states(db, requester, events)

    assert len(states) == 4
    assert all(state == {"action": "no_recording"} for state in states.values())
    assert db.scalars.await_count == 2


@pytest.mark.asyncio
async def test_unsubscribe_cancels_pending_jobs_without_deleting_history():
    from app.api.users import unsubscribe

    user = SimpleNamespace(is_subscribed=True, subscribed_at=datetime.now(timezone.utc), graph_drive_id="drive")
    db = AsyncMock()
    db.scalar.return_value = user

    result = await unsubscribe(db=db, upn="user@example.com")

    assert result.is_subscribed is False
    statement = db.execute.await_args.args[0]
    sql = str(statement)
    assert sql.startswith("UPDATE recording_jobs")
    assert "recording_jobs.status" in sql
    assert "DELETE" not in sql
    assert user.is_subscribed is False
    db.commit.assert_awaited_once()


@respx.mock
@pytest.mark.asyncio
async def test_recording_folder_recurses_and_deduplicates_mp4(monkeypatch):
    from app.graph import client

    base = "https://graph.microsoft.com/v1.0/drives/drive-nested"
    monkeypatch.setattr(client, "_mock_enabled", lambda: False)
    monkeypatch.setattr(client, "get_token", lambda: "token")
    respx.get(f"{base}/root:/Recordings:/children").mock(return_value=httpx.Response(200, json={
        "value": [
            {"id": "direct", "name": "direct.mp4"},
            {"id": "folder-a", "name": "2026", "folder": {}},
        ]
    }))
    respx.get(f"{base}/root:/Documents/Recordings:/children").mock(return_value=httpx.Response(404))
    respx.get(f"{base}/root/children?$select=id,name,folder,parentReference").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    respx.get(f"{base}/items/folder-a/children").mock(return_value=httpx.Response(200, json={
        "value": [
            {"id": "nested", "name": "nested.MP4"},
            {"id": "direct", "name": "duplicate.mp4"},
            {"id": "outside", "name": "notes.txt"},
        ]
    }))

    result = await client.list_recordings_folder("drive-nested")

    assert {item["id"] for item in result} == {"direct", "nested"}
