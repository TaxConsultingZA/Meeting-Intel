"""Tests for app/pipeline/transcribe.py — TranscriptSegment, MockTranscriber, factory."""
import asyncio
import threading
from unittest.mock import Mock

import pytest
from app.pipeline.transcribe import TranscriptSegment, MockTranscriber, get_transcriber, AssemblyAITranscriber
from app.services.job_control import JobCancelled


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


def test_cancel_before_upload_never_calls_provider(monkeypatch):
    transcriber = AssemblyAITranscriber()
    upload = Mock()
    monkeypatch.setattr(transcriber, "_upload", upload)
    stop = threading.Event()
    stop.set()
    with pytest.raises(JobCancelled):
        transcriber._transcribe_sync("not-a-real-file", stop)
    upload.assert_not_called()


async def test_cancel_during_upload_waits_for_drain_and_never_submits(monkeypatch):
    transcriber = AssemblyAITranscriber()
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()

    def upload(_):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5), "Test did not release the fake upload"
        return "fake-upload"

    submit = Mock()
    monkeypatch.setattr(transcriber, "_upload", upload)
    monkeypatch.setattr(transcriber, "_submit", submit)
    task = asyncio.create_task(transcriber.transcribe("not-a-real-file"))
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()  # Still cancel-requested while upload drains.
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    submit.assert_not_called()
