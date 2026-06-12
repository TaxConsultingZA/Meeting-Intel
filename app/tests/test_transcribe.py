"""Tests for app/pipeline/transcribe.py — TranscriptSegment, MockTranscriber, factory."""
import pytest
from app.pipeline.transcribe import TranscriptSegment, MockTranscriber, get_transcriber, AssemblyAITranscriber


class TestTranscriptSegment:
    def test_fields_stored(self):
        seg = TranscriptSegment("Speaker A", "Hello.", 0.0, 2.5)
        assert seg.speaker == "Speaker A"
        assert seg.text == "Hello."
        assert seg.start == 0.0
        assert seg.end == 2.5


class TestMockTranscriber:
    async def test_returns_list_of_segments(self):
        t = MockTranscriber()
        segments = await t.transcribe("fake.mp4")
        assert isinstance(segments, list)
        assert len(segments) > 0

    async def test_segments_have_speaker_labels(self):
        t = MockTranscriber()
        segments = await t.transcribe("fake.mp4")
        for seg in segments:
            assert seg.speaker.startswith("Speaker")
            assert isinstance(seg.text, str)
            assert seg.start >= 0
            assert seg.end > seg.start


class TestGetTranscriber:
    def test_mock_impl_returns_mock_transcriber(self, monkeypatch):
        from app import config
        monkeypatch.setattr(config.get_settings(), "transcriber_impl", "mock")
        t = get_transcriber()
        assert isinstance(t, MockTranscriber)

    def test_assemblyai_impl_returns_assemblyai_transcriber(self, monkeypatch):
        from app import config
        monkeypatch.setattr(config.get_settings(), "transcriber_impl", "assemblyai")
        t = get_transcriber()
        assert isinstance(t, AssemblyAITranscriber)
