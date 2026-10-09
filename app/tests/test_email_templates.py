"""Tests for app/email_templates.py — HTML helper functions and full email build."""
import pytest
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
