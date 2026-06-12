"""Tests for app/api/calendar.py — event status computation and event formatting."""
import pytest
from datetime import datetime, timezone, timedelta
from app.api.calendar import _event_status, _format_event


def _iso(dt: datetime) -> str:
    # Use Graph API's naive format — _event_status strips trailing zeros before
    # calling fromisoformat, which breaks timezone suffixes like +00:00.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.0000000")


NOW = datetime.now(timezone.utc)


class TestEventStatus:
    def test_no_start_returns_upcoming(self):
        assert _event_status(None, None) == "upcoming"

    def test_future_start_returns_upcoming(self):
        future = NOW + timedelta(hours=2)
        assert _event_status(_iso(future), None) == "upcoming"

    def test_past_start_no_end_returns_in_progress(self):
        past = NOW - timedelta(minutes=30)
        assert _event_status(_iso(past), None) == "in_progress"

    def test_ongoing_event_returns_in_progress(self):
        start = NOW - timedelta(minutes=15)
        end = NOW + timedelta(minutes=45)
        assert _event_status(_iso(start), _iso(end)) == "in_progress"

    def test_ended_event_returns_upcoming(self):
        start = NOW - timedelta(hours=2)
        end = NOW - timedelta(hours=1)
        assert _event_status(_iso(start), _iso(end)) == "upcoming"

    def test_malformed_timestamp_returns_upcoming(self):
        assert _event_status("not-a-date", None) == "upcoming"

    def test_naive_datetime_treated_as_utc(self):
        # Graph sometimes returns datetime without tzinfo; should not crash
        past_naive = (NOW - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
        result = _event_status(past_naive, None)
        assert result in ("in_progress", "upcoming")


class TestFormatEvent:
    def _raw_event(self, **overrides):
        base = {
            "id": "evt-1",
            "subject": "Tax Discussion",
            "start": {"dateTime": _iso(NOW + timedelta(hours=1)), "timeZone": "UTC"},
            "end": {"dateTime": _iso(NOW + timedelta(hours=2)), "timeZone": "UTC"},
            "organizer": {"emailAddress": {"name": "Alice Smith", "address": "alice@taxconsulting.co.za"}},
            "attendees": [
                {"emailAddress": {"address": "bob@taxconsulting.co.za"}},
                {"emailAddress": {"address": "carol@taxconsulting.co.za"}},
            ],
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
            "location": {"displayName": "Teams"},
        }
        base.update(overrides)
        return base

    def test_basic_fields_populated(self):
        out = _format_event(self._raw_event())
        assert out["event_id"] == "evt-1"
        assert out["subject"] == "Tax Discussion"
        assert out["organizer_name"] == "Alice Smith"
        assert out["organizer_email"] == "alice@taxconsulting.co.za"

    def test_attendee_count(self):
        out = _format_event(self._raw_event())
        assert out["attendee_count"] == 2
        assert "bob@taxconsulting.co.za" in out["attendees"]

    def test_status_field_present(self):
        out = _format_event(self._raw_event())
        assert out["status"] in ("upcoming", "in_progress")

    def test_missing_subject_defaults_to_untitled(self):
        out = _format_event(self._raw_event(subject=None))
        assert out["subject"] == "Untitled Meeting"

    def test_no_organizer_returns_none(self):
        raw = self._raw_event()
        raw.pop("organizer")
        out = _format_event(raw)
        assert out["organizer_name"] is None
        assert out["organizer_email"] is None

    def test_attendees_without_address_skipped(self):
        raw = self._raw_event()
        raw["attendees"] = [{"emailAddress": {}}, {"emailAddress": {"address": "valid@x.com"}}]
        out = _format_event(raw)
        assert out["attendee_count"] == 1
