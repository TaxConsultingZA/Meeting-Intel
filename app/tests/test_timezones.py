from datetime import datetime, timezone
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from app.utils.timezones import parse_graph_datetime, utc_iso
from app.api.calendar import _format_event, _event_status
from app.services.meeting_matching import recording_datetime
from app.services import recording_enrichment


@pytest.mark.parametrize("zone,wall,utc", [
    ("South Africa Standard Time", "2026-08-28T00:30:00.0000000", "2026-08-27T22:30:00Z"),
    ("Africa/Johannesburg", "2026-08-28T10:00:00", "2026-08-28T08:00:00Z"),
    ("China Standard Time", "2026-08-28T00:30:00", "2026-08-27T16:30:00Z"),
    ("Asia/Shanghai", "2026-08-28T10:00:00", "2026-08-28T02:00:00Z"),
    ("UTC", "2026-08-28T10:00:00.0000000", "2026-08-28T10:00:00Z"),
    ("China Standard Time", "2026-08-28T10:00:00+02:00", "2026-08-28T08:00:00Z"),
    ("South Africa Standard Time", "2026-08-28T10:00:00Z", "2026-08-28T10:00:00Z"),
    ("Eastern Standard Time", "2026-07-01T10:00:00", "2026-07-01T14:00:00Z"),
    ("Eastern Standard Time", "2026-01-01T10:00:00", "2026-01-01T15:00:00Z"),
])
def test_graph_zone_and_explicit_offset(zone, wall, utc):
    assert utc_iso({"dateTime": wall, "timeZone": zone}) == utc


def test_unknown_zone_is_not_silently_utc():
    assert parse_graph_datetime({"dateTime": "2026-01-01T10:00:00", "timeZone": "Unknown"}) is None


def test_calendar_response_is_unambiguous_utc():
    out = _format_event({"start": {"dateTime": "2026-08-28T00:30:00", "timeZone": "China Standard Time"},
                         "end": {"dateTime": "2026-08-28T01:00:00", "timeZone": "China Standard Time"}})
    assert out["start"] == "2026-08-27T16:30:00Z"
    assert out["end"] == "2026-08-27T17:00:00Z" and out["start_tz"] == "UTC"
    assert out["source_timezone"] == "China Standard Time"


def test_graph_fractional_offset_is_not_stripped():
    assert _event_status("2000-01-01T00:00:00.0000000+00:00", None) == "in_progress"


def test_filename_stamp_never_overrides_graph_instant():
    assert recording_datetime("Meeting-20260828_103000.mp4", {"createdDateTime": "2026-08-28T08:30:00Z"}).hour == 8
    assert recording_datetime("Meeting-20260828_103000.mp4") is None


async def test_enrichment_uses_matching_signatures_and_keeps_names(monkeypatch):
    meeting = SimpleNamespace(recorded_at=None, organizer_upn="owner@example.test", extracted_json={})
    monkeypatch.setattr(recording_enrichment.graph, "get_drive_item", AsyncMock(return_value={"name": "Planning.mp4", "createdDateTime": "2026-08-28T08:00:00Z"}))
    monkeypatch.setattr(recording_enrichment, "events_between", AsyncMock(return_value=[{
        "id": "event", "subject": "Planning",
        "start": {"dateTime": "2026-08-28T10:00:00", "timeZone": "South Africa Standard Time"},
        "organizer": {"emailAddress": {"address": "owner@example.test", "name": "Owner"}},
        "attendees": [{"emailAddress": {"address": "person@example.test", "name": "Person"}}],
    }]))
    await recording_enrichment.enrich_recording_from_outlook(meeting, "d", "i")
    assert meeting.recorded_at == datetime(2026, 8, 28, 8, tzinfo=timezone.utc)
    assert meeting.extracted_json["attendees"] == ["Person", "Owner"]
    assert meeting.extracted_json["speaker_candidates"][0]["email"] == "person@example.test"
