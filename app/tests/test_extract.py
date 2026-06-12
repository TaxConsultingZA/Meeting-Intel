"""Tests for app/pipeline/extract.py — transcript formatting, JSON parsing, mock extractor."""
import json
import pytest
from app.pipeline.transcribe import TranscriptSegment
from app.pipeline.extract import _transcript_to_text, _parse_raw, MockExtractor, get_extractor
from app.models import Confidence


SEG_A = TranscriptSegment("Speaker A", "Let's review the action items.", 0.0, 3.0)
SEG_B = TranscriptSegment("Speaker B", "I'll handle the SARS submission.", 3.0, 6.0)


class TestTranscriptToText:
    def test_formats_speaker_labels(self):
        text = _transcript_to_text([SEG_A, SEG_B])
        assert "[Speaker A] Let's review the action items." in text
        assert "[Speaker B] I'll handle the SARS submission." in text

    def test_empty_segments_returns_empty_string(self):
        assert _transcript_to_text([]) == ""

    def test_segments_joined_with_newlines(self):
        text = _transcript_to_text([SEG_A, SEG_B])
        lines = text.split("\n")
        assert len(lines) == 2


class TestParseRaw:
    def _minimal_json(self, **overrides) -> str:
        data = {
            "objective": "Discuss compliance.",
            "meeting_time": None,
            "attendees": ["Speaker A"],
            "apologies": [],
            "platform": "Microsoft Teams",
            "speaker_highlights": [],
            "discussion_points": [],
            "action_items": [],
            "deliverables": [],
            "risks": [],
            "next_steps": [],
            "next_meeting": None,
            "summary": "Short summary.",
        }
        data.update(overrides)
        return json.dumps(data)

    def test_parses_objective(self):
        result = _parse_raw(self._minimal_json())
        assert result.objective == "Discuss compliance."

    def test_strips_markdown_code_fence(self):
        fenced = "```json\n" + self._minimal_json() + "\n```"
        result = _parse_raw(fenced)
        assert result.objective == "Discuss compliance."

    def test_strips_plain_code_fence(self):
        fenced = "```\n" + self._minimal_json() + "\n```"
        result = _parse_raw(fenced)
        assert result.objective == "Discuss compliance."

    def test_missing_objective_defaults_to_empty(self):
        data = json.loads(self._minimal_json())
        del data["objective"]
        result = _parse_raw(json.dumps(data))
        assert result.objective == ""

    def test_action_items_parsed(self):
        data = json.loads(self._minimal_json())
        data["action_items"] = [
            {"action": "Submit SARS return", "assigned_to": "Alice",
             "confidence": "high", "due_date": "end of month"}
        ]
        result = _parse_raw(json.dumps(data))
        assert len(result.action_items) == 1
        assert result.action_items[0].action == "Submit SARS return"
        assert result.action_items[0].confidence == Confidence.high


class TestMockExtractor:
    async def test_returns_result(self):
        extractor = MockExtractor()
        result = await extractor.extract([SEG_A, SEG_B])
        assert result.objective != ""
        assert len(result.action_items) > 0

    async def test_action_items_have_required_fields(self):
        extractor = MockExtractor()
        result = await extractor.extract([SEG_A])
        for item in result.action_items:
            assert item.action
            assert item.confidence in (Confidence.high, Confidence.medium, Confidence.low)


class TestGetExtractor:
    def test_returns_mock_for_unknown_impl(self, monkeypatch):
        from app import config
        settings = config.get_settings()
        monkeypatch.setattr(settings, "extractor_impl", "mock")
        extractor = get_extractor()
        assert isinstance(extractor, MockExtractor)
