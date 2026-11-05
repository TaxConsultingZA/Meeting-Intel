from datetime import datetime, timezone
from app.services.meeting_dates import card_date


def test_verified_identity_uses_calendar_not_recording_clock():
    result = card_date(None, {"recording_identity": {
        "status": "linked", "evidence": "unique_exact_title_time_owner_stable_id",
        "event": {"id": "synthetic", "start": {"dateTime": "2026-10-30T09:30:00.0000000", "timeZone": "UTC"}},
        "recorded_at": "2026-10-30T09:52:46Z"}})
    assert result["source"] == "meeting"
    assert result["value"] == "2026-10-30T09:30:00+00:00"


def test_unmatched_event_is_not_a_meeting_date():
    result = card_date(None, {"recording_identity": {"status": "unmatched", "event": {"id": "wrong", "start": "2026-10-30T09:30:00Z"}, "recorded_at": "2026-10-30T09:52:46Z"}})
    assert result["source"] == "recording"
    assert "09:52:46" in result["value"]


def test_legacy_calendar_and_standalone_recording():
    instant = datetime(2026, 10, 30, 9, 30, tzinfo=timezone.utc)
    assert card_date(instant, {"outlook_event_id": "verified"})["source"] == "meeting"
    assert card_date(instant, {})["source"] == "recording"
    assert card_date(None, {"meeting_time": "2026-10-30T09:30:00Z"})["source"] == "unavailable"


def test_missing_invalid_and_unknown_zone_never_invent_dates():
    for data in [{}, {"recording_identity": {"recorded_at": "garbage"}},
                 {"t5_calendar_event": {"id": "verified", "start": {"dateTime": "2026-10-30T09:30:00", "timeZone": "unknown"}}}]:
        assert card_date(None, data)["value"] is None
        assert card_date(None, data)["reason"]


def test_owner_verified_event_timezone_and_offset():
    for start in [{"dateTime": "2026-10-30T11:30:00", "timeZone": "South Africa Standard Time"}, "2026-10-30T11:30:00+02:00"]:
        assert card_date(None, {"t5_calendar_event": {"id": "verified", "start": start}})["value"] == "2026-10-30T09:30:00+00:00"


def test_date_provenance_survives_list_and_historical_serialization():
    from types import SimpleNamespace
    from uuid import uuid4
    from app.api.reviews import _to_list_out, _to_historical_out
    from app.models import ProcessingState
    meeting = SimpleNamespace(id=uuid4(), title="Synthetic", recorded_at=None,
        extracted_json={"recording_identity": {"status": "linked",
            "evidence": "unique_exact_title_time_owner_stable_id", "event": {
                "id": "synthetic", "start": {"dateTime": "2026-10-30T09:30:00.0000000", "timeZone": "UTC"}}}},
        participants=[], attendees_raw=[], organizer_upn="owner@example.test",
        state=ProcessingState.awaiting_review, error=None)
    for result in [_to_list_out(meeting, "owner@example.test"), _to_historical_out(meeting)]:
        assert result.extracted_json is None
        assert result.recorded_at is None
        assert result.card_date.source == "meeting"
        assert "2026-10-30T09:30:00Z" in result.model_dump_json()


def test_uncertain_identity_and_ai_time_never_supply_meeting_start():
    for status in ["unmatched", "ambiguous", "linked"]:
        result = card_date(None, {"recording_identity": {"status": status, "evidence": "insufficient", "event": {"id": "wrong", "start": "2026-10-30T09:30:00Z"}}, "outlook_event_id": "legacy", "meeting_time": "2026-10-30T09:30:00Z"})
        assert result["date_source"] == "unavailable"


def test_raw_time_and_event_id_contract():
    raw = {"dateTime": "2026-10-30T09:30:00.0000000", "timeZone": "UTC"}
    result = card_date(None, {"t5_calendar_event": {"id": "synthetic", "start": raw}})
    assert result["raw_time"] == raw
    assert result["event_id"] == "synthetic"
    assert result["date_source"] == "meeting"


def test_current_ledger_unlink_and_owner_relink_supersede_saved_event():
    saved = {"t5_calendar_event": {"id": "old", "start": "2026-10-30T09:30:00Z"}}
    independent = {"status": "independent", "recorded_at": "2026-10-30T09:52:46Z"}
    assert card_date(None, saved, independent)["date_source"] == "recording"
    linked = {"status": "linked", "decided_by": "owner@example.test", "decided_at": "2026-10-30T12:00:00Z", "event": {"id": "new", "start": "2026-10-31T09:30:00Z"}}
    assert card_date(None, saved, linked)["event_id"] == "new"
    assert card_date(None, saved, {"status": "needs_review"})["date_source"] == "unavailable"
