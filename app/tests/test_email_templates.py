"""Tests for app/email_templates.py — HTML helper functions and full email build."""
import pytest
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
        m.action_items = []
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
