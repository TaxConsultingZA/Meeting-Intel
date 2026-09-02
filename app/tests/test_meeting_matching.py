from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import recording_enrichment
from app.services.meeting_matching import match_calendar_event


RECORDED_AT = datetime(2026, 9, 1, 8, 41, 58, tzinfo=timezone.utc)


def _event(subject: str, start: str, end: str) -> dict:
    return {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
    }


def test_test_recording_prefers_title_match_over_nearby_unrelated_meeting():
    trust_it3 = _event(
        "Trust IT3(t) Reporting – Practical Classroom Session",
        "2026-09-01T08:00:00Z",
        "2026-09-01T09:30:00Z",
    )
    test = _event(
        "已取消: Test",
        "2026-09-01T08:30:00Z",
        "2026-09-01T09:00:00Z",
    )

    matched = match_calendar_event(
        "Test-20260901_164158-会议记录.mp4", RECORDED_AT, [trust_it3, test]
    )

    assert matched is test


def test_nearby_unrelated_meeting_is_not_forced_when_no_reasonable_title_exists():
    trust_it3 = _event(
        "Trust IT3(t) Reporting – Practical Classroom Session",
        "2026-09-01T08:00:00Z",
        "2026-09-01T09:30:00Z",
    )

    assert match_calendar_event(
        "Test-20260901_164158-会议记录.mp4", RECORDED_AT, [trust_it3]
    ) is None


async def test_enrichment_falls_back_to_other_subscribed_calendar(monkeypatch):
    trust_it3 = {
        "id": "trust",
        **_event(
            "Trust IT3(t) Reporting – Practical Classroom Session",
            "2026-09-01T08:00:00Z",
            "2026-09-01T09:30:00Z",
        ),
    }
    test = {
        "id": "test",
        **_event(
            "已取消: Test", "2026-09-01T08:30:00Z", "2026-09-01T09:00:00Z"
        ),
    }
    meeting = SimpleNamespace(
        recorded_at=None,
        organizer_upn="owner@example.test",
        title=None,
        attendees_raw=None,
        extracted_json={},
    )
    monkeypatch.setattr(
        recording_enrichment.graph,
        "get_drive_item",
        AsyncMock(return_value={
            "name": "Test-20260901_164158-会议记录.mp4",
            "createdDateTime": "2026-09-01T08:41:58Z",
        }),
    )
    calendars = AsyncMock(side_effect=[[trust_it3], [test]])
    monkeypatch.setattr(recording_enrichment, "events_between", calendars)

    await recording_enrichment.enrich_recording_from_outlook(
        meeting,
        "drive",
        "item",
        candidate_upns=["owner@example.test", "attendee@example.test"],
    )

    assert calendars.await_count == 2
    assert meeting.title == "已取消: Test"
    assert meeting.extracted_json["outlook_event_id"] == "test"
