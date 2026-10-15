"""Tests for app/email_templates.py — HTML helper functions and full email build."""
import pytest
from datetime import datetime, timedelta, timezone
from html import escape
from types import SimpleNamespace
from app.email_templates import _th, _td, _empty_row, _section_heading, _detail_table, build_meeting_email


class TestTh:
    def test_contains_text(self):
        html = _th("Action Required")
        assert "Action Required" in html

    def test_navy_background(self):
        html = _th("Header")
        assert "#003366" in html

    def test_width_attribute_included_when_provided(self):
        html = _th("Col", width="200")
        assert 'width="200"' in html

    def test_no_width_attribute_when_omitted(self):
        html = _th("Col")
        assert 'width=""' not in html


class TestTd:
    def test_contains_text(self):
        html = _td("Some value")
        assert "Some value" in html

    def test_empty_string_shows_placeholder(self):
        html = _td("")
        assert "—" in html or "AAAAAA" in html

    def test_alt_row_uses_different_background(self):
        normal = _td("x", alt=False)
        alt = _td("x", alt=True)
        assert normal != alt

    def test_bold_applies_font_weight(self):
        html = _td("x", bold=True)
        assert "font-weight:600" in html


class TestEmptyRow:
    def test_spans_correct_columns(self):
        html = _empty_row(4)
        assert 'colspan="4"' in html

    def test_contains_none_identified_text(self):
        html = _empty_row(3)
        assert "None identified" in html


class TestSectionHeading:
    def test_contains_title(self):
        html = _section_heading("Action Items")
        assert "Action Items" in html

    def test_gold_border_present(self):
        html = _section_heading("Test")
        assert "#C9A52C" in html


class TestDetailTable:
    def test_renders_all_rows(self):
        html = _detail_table([("Title", "Meeting A"), ("Date", "2026-06-02")])
        assert "Title" in html
        assert "Meeting A" in html
        assert "Date" in html
        assert "2026-06-02" in html

    def test_empty_value_shows_placeholder(self):
        html = _detail_table([("Field", "")])
        assert "—" in html or "AAAAAA" in html


class TestBuildMeetingEmail:
    def _mock_meeting(self):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.title = "Q2 Tax Review"
        m.recorded_at = datetime(2025, 1, 15, 10, tzinfo=timezone.utc)
        m.organizer_upn = "stanley@taxconsulting.co.za"
        m.summary = "Discussed Q2 obligations."
        m.extracted_json = {
            "objective": "Review Q2 tax obligations.",
            "meeting_time": "10:00 AM",
            "attendees": ["Stanley", "Mieke"],
            "apologies": [],
            "platform": "Microsoft Teams",
            "speaker_highlights": [],
            "discussion_points": [{"topic": "VAT", "summary": "All good.", "outcome": "No action."}],
            "action_items": [{"action": "Submit VAT return", "assigned_to": "Stanley",
                              "department": None, "reason": "Deadline", "expected_outcome": "Filed",
                              "due_date": "30 June", "confidence": "high", "source_quote": None}],
            "deliverables": [],
            "risks": [],
            "next_steps": ["Follow up on VAT"],
            "next_meeting": {"proposed_date": "2026-07-01", "proposed_time": "10:00", "agenda_focus": "Q3"},
            "summary": "Q2 review done.",
        }
        m.action_items = [SimpleNamespace(
            task="Submit VAT return", owner="Stanley", deadline_text="30 June",
            deadline_iso=None, raw=m.extracted_json["action_items"][0],
        )]
        return m

    def test_returns_tuple_of_subject_and_html(self):
        subject, html = build_meeting_email(self._mock_meeting())
        assert isinstance(subject, str)
        assert isinstance(html, str)

    def test_subject_contains_title(self):
        subject, _ = build_meeting_email(self._mock_meeting())
        assert "Q2 Tax Review" in subject

    def test_html_contains_meeting_title(self):
        _, html = build_meeting_email(self._mock_meeting())
        assert "Q2 Tax Review" in html

    def test_html_contains_action_items(self):
        _, html = build_meeting_email(self._mock_meeting())
        assert "Submit VAT return" in html

    def test_reviewed_fields_override_both_extraction_snapshots(self):
        meeting = self._mock_meeting()
        item = meeting.action_items[0]
        item.task = "Reviewed filing task"
        item.owner = "Reviewed owner"
        item.deadline_iso = "2026-07-15"
        _, html = build_meeting_email(meeting)
        assert "Reviewed filing task" in html
        assert "Reviewed owner" in html
        assert "2026-07-15" in html
        assert "Submit VAT return" not in html
        assert "30 June" not in html
        assert "Deadline" in html and "Filed" in html
        assert item.raw["action"] == "Submit VAT return"

    def test_cleared_fields_do_not_fall_back_to_extraction(self):
        meeting = self._mock_meeting()
        item = meeting.action_items[0]
        item.owner = None
        item.deadline_text = None
        item.deadline_iso = None
        _, html = build_meeting_email(meeting)
        action_table = html.split("<!-- ACTION ITEMS -->")[1].split("<!-- DELIVERABLES -->")[0]
        assert "Stanley" not in action_table
        assert "30 June" not in action_table

    def test_empty_reviewed_collection_does_not_resurrect_snapshot_actions(self):
        meeting = self._mock_meeting()
        meeting.action_items = []
        _, html = build_meeting_email(meeting)
        assert "Submit VAT return" not in html

    def test_legacy_rows_render_without_extraction_json_or_raw(self):
        meeting = self._mock_meeting()
        meeting.extracted_json = None
        meeting.action_items[0].raw = None
        _, html = build_meeting_email(meeting)
        assert "Submit VAT return" in html
        assert "Stanley" in html and "30 June" in html

    def test_html_contains_discussion_points(self):
        _, html = build_meeting_email(self._mock_meeting())
        assert "VAT" in html

    def test_html_contains_organiser(self):
        _, html = build_meeting_email(self._mock_meeting())
        assert "stanley@taxconsulting.co.za" in html

    def test_html_is_valid_structure(self):
        _, html = build_meeting_email(self._mock_meeting())
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_uses_historical_recording_date_and_stable_content(self):
        meeting = self._mock_meeting()
        first = build_meeting_email(meeting)
        assert "Date (UTC)" in first[1]
        assert "15 January 2025" in first[1]
        assert build_meeting_email(meeting) == first

    @pytest.mark.parametrize("recorded_at, expected", [
        (datetime(2025, 1, 15, 0, 30, tzinfo=timezone(timedelta(hours=8))), "14 January 2025"),
        (datetime(2025, 1, 15, 23, 30, tzinfo=timezone(timedelta(hours=-5))), "16 January 2025"),
        (datetime(2025, 1, 15, 10), "15 January 2025"),
        (None, "Not available"),
    ])
    def test_date_normalizes_to_utc_and_never_invents_missing_date(self, recorded_at, expected):
        meeting = self._mock_meeting()
        meeting.recorded_at = recorded_at
        assert expected in build_meeting_email(meeting)[1]

    def test_missing_legacy_timestamp_is_supported(self):
        meeting = self._mock_meeting()
        del meeting.recorded_at
        assert "Not available" in build_meeting_email(meeting)[1]

    @pytest.mark.parametrize("field", [
        "title", "organizer_upn", "summary", "objective", "meeting_time", "platform",
        "attendees", "apologies", "speaker", "role", "key_points",
        "topic", "discussion_summary", "outcome", "task", "owner", "deadline_iso", "deadline_text",
        "department", "reason", "expected_outcome", "deliverable", "responsible",
        "delivery_method", "due_date", "deliverable_outcome", "risk_item", "impact", "resolution",
        "risk_owner", "next_steps", "proposed_date", "proposed_time", "agenda_focus",
    ])
    def test_dynamic_meeting_fields_are_literal_text(self, field):
        meeting = self._mock_meeting()
        payload = '<svg onload="alert(1)">A & B \'quoted\'</svg>'
        data = meeting.extracted_json
        action = meeting.action_items[0]
        if field in {"title", "organizer_upn", "summary"}:
            setattr(meeting, field, payload)
            if field == "summary":
                data["objective"] = None
        elif field in {"objective", "meeting_time", "platform"}:
            data[field] = payload
        elif field in {"attendees", "apologies", "next_steps"}:
            data[field] = [payload]
        elif field in {"speaker", "role", "key_points"}:
            data["speaker_highlights"] = [{"speaker": "Alex", "role": "Owner", "key_points": []}]
            data["speaker_highlights"][0][field] = [payload] if field == "key_points" else payload
        elif field in {"topic", "discussion_summary", "outcome"}:
            data["discussion_points"][0]["summary" if field == "discussion_summary" else field] = payload
        elif field in {"task", "owner", "deadline_iso", "deadline_text"}:
            setattr(action, field, payload)
        elif field in {"department", "reason", "expected_outcome"}:
            action.raw[field] = payload
        elif field in {"deliverable", "responsible", "delivery_method", "due_date", "deliverable_outcome"}:
            data["deliverables"] = [{"expected_outcome" if field == "deliverable_outcome" else field: payload}]
        elif field in {"risk_item", "impact", "resolution", "risk_owner"}:
            data["risks"] = [{ {"risk_item": "item", "risk_owner": "owner"}.get(field, field): payload}]
        else:
            data["next_meeting"][field] = payload
        subject, html = build_meeting_email(meeting)
        assert payload not in html
        assert escape(payload, quote=True) in html
        assert "<table" in html and "</table>" in html
        if field == "title":
            assert subject.endswith(payload)  # Subjects are plain text, not HTML.


def test_helpers_escape_text_once_and_keep_template_placeholders():
    text = '<b>R&D "quoted"</b>'
    for html in (_td(text), _th(text), _section_heading(text), _detail_table([(text, text)])):
        assert escape(text) in html
        assert text not in html
        assert "&amp;lt;b" not in html
    assert "<span" in _td(None)


def test_welcome_email_escapes_dynamic_text_and_attribute_values():
    from app.email_templates import build_welcome_email
    payload = '<svg onload="alert(1)">R&D</svg>'
    url = 'https://example.com/?a=1&b="quoted"'
    _, html = build_welcome_email("user@example.com", payload, payload, url)
    assert payload not in html
    assert f"<strong>{escape(payload)}</strong>" in html
    assert f'href="{escape(url)}"' in html
