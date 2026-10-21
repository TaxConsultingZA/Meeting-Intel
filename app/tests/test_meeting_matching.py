from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
        "attendees": [{"emailAddress": {"address": upn}} for upn in
                      ("owner@example.test", "attendee@example.test")],
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


def test_missing_recording_time_never_guesses_from_filename():
    from app.services.meeting_matching import recording_datetime
    name = "Review-20260901_084158-Meeting Recording.mp4"
    assert recording_datetime(name, {}) is None
    assert match_calendar_event(name, None, [
        _event("Review", "2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z")
    ]) is None


def test_equal_title_and_time_with_distinct_meetings_is_ambiguous_in_either_order():
    first = {"id": "first", "iCalUId": "first", **_event(
        "Review", "2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z")}
    second = {**first, "id": "second", "iCalUId": "second"}
    assert match_calendar_event("Review.mp4", RECORDED_AT, [first, second]) is None
    assert match_calendar_event("Review.mp4", RECORDED_AT, [second, first]) is None
    copy = {**first, "id": "mailbox-copy"}
    assert match_calendar_event("Review.mp4", RECORDED_AT, [first, copy]) is first


async def test_external_creator_calendar_failure_uses_authorised_attendee_copy(monkeypatch):
    event = {"id": "attendee-copy", **_event(
        "Review", "2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z"),
        "organizer": {"emailAddress": {"address": "external@example.test"}},
        "attendees": [{"emailAddress": {"address": "attendee@example.test"}}]}
    meeting = SimpleNamespace(recorded_at=None, organizer_upn="external@example.test",
        title=None, attendees_raw=None, extracted_json={})
    monkeypatch.setattr(recording_enrichment.graph, "get_drive_item", AsyncMock(
        return_value={"name": "Review.mp4", "createdDateTime": RECORDED_AT.isoformat()}))
    calendars = AsyncMock(side_effect=[RuntimeError("mailbox inaccessible"), [event]])
    monkeypatch.setattr(recording_enrichment, "events_between", calendars)
    await recording_enrichment.enrich_recording_from_outlook(
        meeting, "drive", "item", candidate_upns=["attendee@example.test"])
    assert calendars.await_count == 2
    assert meeting.organizer_upn == "external@example.test"
    assert meeting.extracted_json["outlook_event_id"] == "attendee-copy"
    assert meeting.attendees_raw[0]["emailAddress"]["address"] == "attendee@example.test"


async def test_inaccessible_calendars_do_not_invent_meeting_identity(monkeypatch):
    meeting = SimpleNamespace(recorded_at=None, organizer_upn="external@example.test",
        title="Review.mp4", attendees_raw=None, extracted_json={})
    monkeypatch.setattr(recording_enrichment.graph, "get_drive_item", AsyncMock(
        return_value={"name": "Review.mp4", "createdDateTime": RECORDED_AT.isoformat()}))
    monkeypatch.setattr(recording_enrichment, "events_between",
        AsyncMock(side_effect=RuntimeError("mailbox inaccessible")))
    await recording_enrichment.enrich_recording_from_outlook(
        meeting, "drive", "item", candidate_upns=["attendee@example.test"])
    assert meeting.title == "Review.mp4"
    assert meeting.organizer_upn == "external@example.test"
    assert meeting.attendees_raw is None
    assert "outlook_event_id" not in meeting.extracted_json


async def test_fallback_same_title_time_without_recording_identity_is_not_matched(monkeypatch):
    meeting = SimpleNamespace(recorded_at=None, organizer_upn="external@example.test",
        title="Review.mp4", attendees_raw=None, extracted_json={})
    unrelated = {"id": "unrelated", **_event(
        "Review", "2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z"),
        "organizer": {"emailAddress": {"address": "other@example.test"}}}
    monkeypatch.setattr(recording_enrichment.graph, "get_drive_item", AsyncMock(
        return_value={"name": "Review.mp4", "createdDateTime": RECORDED_AT.isoformat()}))
    monkeypatch.setattr(recording_enrichment, "events_between",
        AsyncMock(side_effect=[RuntimeError("mailbox inaccessible"), [unrelated]]))
    await recording_enrichment.enrich_recording_from_outlook(
        meeting, "drive", "item", candidate_upns=["attendee@example.test"])
    assert meeting.title == "Review.mp4"
    assert meeting.attendees_raw is None
    assert "outlook_event_id" not in meeting.extracted_json


@pytest.mark.parametrize("kind", ["mailbox_not_participant", "declined_creator", "resource_creator", "cancelled"])
async def test_fallback_requires_active_human_recording_and_mailbox_participants(monkeypatch, kind):
    recording_identity = "creator@example.test"
    mailbox = "attendee@example.test"
    attendees = [{"emailAddress": {"address": recording_identity}},
                 {"emailAddress": {"address": mailbox}}]
    event = {"id": "unsafe", **_event(
        "Review", "2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z"),
        "organizer": {"emailAddress": {"address": "host@external.example"}},
        "attendees": attendees}
    if kind == "mailbox_not_participant":
        attendees.pop()
    elif kind == "declined_creator":
        attendees[0]["status"] = {"response": "declined"}
    elif kind == "resource_creator":
        attendees[0]["type"] = "resource"
    else:
        event["isCancelled"] = True
    meeting = SimpleNamespace(recorded_at=None, organizer_upn=recording_identity,
        title="Review.mp4", attendees_raw=None, extracted_json={})
    monkeypatch.setattr(recording_enrichment.graph, "get_drive_item", AsyncMock(
        return_value={"name": "Review.mp4", "createdDateTime": RECORDED_AT.isoformat()}))
    monkeypatch.setattr(recording_enrichment, "events_between",
        AsyncMock(side_effect=[RuntimeError("mailbox inaccessible"), [event]]))
    await recording_enrichment.enrich_recording_from_outlook(
        meeting, "drive", "item", candidate_upns=[mailbox])
    assert meeting.title == "Review.mp4"
    assert meeting.attendees_raw is None
    assert "outlook_event_id" not in meeting.extracted_json


@pytest.mark.parametrize("primary_inaccessible", [False, True])
async def test_enrichment_does_not_reintroduce_declined_or_resource_access_candidates(monkeypatch, primary_inaccessible):
    organizer = "host@external.example"
    subscriber = "attendee@example.test"
    event = {"id": "attendee-copy", **_event(
        "Review", "2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z"),
        "organizer": {"emailAddress": {"address": organizer}},
        "attendees": [
            {"emailAddress": {"address": subscriber}, "status": {"response": "accepted"}},
            {"emailAddress": {"address": "declined@example.test"},
             "status": {"response": "declined"}},
            {"emailAddress": {"address": "room@example.test"}, "type": "resource"},
        ]}
    meeting = SimpleNamespace(recorded_at=None, organizer_upn=organizer,
        title="Review.mp4", attendees_raw=None, extracted_json={})
    monkeypatch.setattr(recording_enrichment.graph, "get_drive_item", AsyncMock(
        return_value={"name": "Review.mp4", "createdDateTime": RECORDED_AT.isoformat()}))
    responses = [RuntimeError("mailbox inaccessible"), [event]] if primary_inaccessible else [[event]]
    calendars = AsyncMock(side_effect=responses)
    monkeypatch.setattr(recording_enrichment, "events_between", calendars)
    await recording_enrichment.enrich_recording_from_outlook(
        meeting, "drive", "item", candidate_upns=[subscriber])
    assert meeting.extracted_json["outlook_event_id"] == "attendee-copy"
    assert meeting.organizer_upn == organizer
    assert {person["emailAddress"]["address"] for person in meeting.attendees_raw} == {organizer, subscriber}
    assert {person["email"] for person in meeting.extracted_json["speaker_candidates"]} == {organizer, subscriber}
    assert calendars.await_count == (2 if primary_inaccessible else 1)
    assert len(event["attendees"]) == 3  # Do not mutate the Calendar snapshot.
