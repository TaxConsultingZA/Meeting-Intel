"""Exercise real pipeline/worker orchestration with fake DB and provider I/O."""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from app.models import ActionItem, Meeting, ProcessingState
from app.pipeline import extract, steps
from app.pipeline.transcribe import MockTranscriber
from app.queue import worker


@pytest.fixture
def pipeline(monkeypatch):
    meeting = Meeting(id=uuid.uuid4(), drive_item_id="offline-item", title="Offline test",
                      organizer_upn="owner@example.test", state=ProcessingState.queued,
                      attendees_raw=["owner@example.test"], extracted_json={})
    snapshots = []
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=lambda stmt: meeting if stmt.column_descriptions[0]["entity"] is Meeting else True)
    db.scalars = AsyncMock(return_value=["owner@example.test"])
    db.execute = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.commit = AsyncMock(side_effect=lambda: snapshots.append((meeting.state, meeting.transcript, deepcopy(meeting.extracted_json))))
    download = AsyncMock()
    mail = AsyncMock()
    transcriber = SimpleNamespace(transcribe=AsyncMock(side_effect=MockTranscriber().transcribe))
    monkeypatch.setattr(steps.graph, "download_drive_item", download)
    monkeypatch.setattr(steps.graph, "get_drive_item", AsyncMock(side_effect=AssertionError("Unexpected Graph metadata")))
    monkeypatch.setattr(steps.graph, "get_event_attendees", AsyncMock(side_effect=AssertionError("Unexpected Graph attendees")))
    monkeypatch.setattr(steps.graph, "send_mail", mail)
    monkeypatch.setattr(steps, "get_transcriber", lambda: transcriber)
    monkeypatch.setattr(steps.settings, "auto_send_email", True)  # Still cannot bypass review.
    return SimpleNamespace(meeting=meeting, db=db, download=download, mail=mail,
                           transcriber=transcriber, snapshots=snapshots)


async def run(p):
    await steps.process_recording(p.db, "offline-item", "offline-drive", owner_upn="owner@example.test")


async def test_mock_pipeline_persists_sections_and_stops_for_human_review(pipeline):
    p = pipeline
    await run(p)
    assert p.meeting.state == ProcessingState.awaiting_review
    data = p.meeting.extracted_json
    assert p.meeting.summary and data["speaker_highlights"][0]["key_points"]
    assert data["action_items"] and data["risks"] and data["next_steps"]
    assert data["raw_transcript"] == p.meeting.transcript
    assert data["transcript_segments"][0]["start"] == 0
    before_ai = next(s for s in p.snapshots if s[0] == ProcessingState.extracting)
    assert before_ai[1] and before_ai[2]["transcript_segments"]
    assert "summary" not in before_ai[2]
    actions = [c.args[0] for c in p.db.add.call_args_list if isinstance(c.args[0], ActionItem)]
    assert actions and all(a.approved is False for a in actions)
    assert p.meeting.approved_by is None and p.meeting.approved_at is None
    p.mail.assert_not_awaited()


@pytest.mark.parametrize("failure", [RuntimeError("provider unavailable"), {"summary": "", "risks": 5}])
async def test_ai_failure_preserves_raw_and_retry_reuses_transcription(monkeypatch, pipeline, failure):
    p = pipeline
    failing = AsyncMock(side_effect=failure) if isinstance(failure, Exception) else AsyncMock(return_value=failure)
    monkeypatch.setattr(steps, "get_extractor", lambda: SimpleNamespace(extract=failing))
    with pytest.raises((RuntimeError, ValueError)):
        await run(p)
    assert p.meeting.state == ProcessingState.failed and p.meeting.error
    raw = p.meeting.transcript
    assert raw and p.meeting.extracted_json["raw_transcript"] == raw
    timestamps = deepcopy(p.meeting.extracted_json["transcript_segments"])
    assert timestamps
    monkeypatch.setattr(steps, "get_extractor", extract.MockExtractor)
    await run(p)
    assert p.meeting.state == ProcessingState.awaiting_review and p.meeting.error is None
    assert p.meeting.transcript == raw and p.meeting.extracted_json["transcript_segments"] == timestamps
    p.download.assert_awaited_once()
    p.transcriber.transcribe.assert_awaited_once()
    p.mail.assert_not_awaited()


async def test_empty_transcription_fails_before_ai(monkeypatch, pipeline):
    p = pipeline
    p.transcriber.transcribe.side_effect = None
    p.transcriber.transcribe.return_value = []
    provider = SimpleNamespace(extract=AsyncMock())
    monkeypatch.setattr(steps, "get_extractor", lambda: provider)
    with pytest.raises(ValueError, match="Transcript is empty"):
        await run(p)
    assert p.meeting.state == ProcessingState.failed
    provider.extract.assert_not_awaited()


async def test_cancel_during_extraction_preserves_raw_without_final_writes(monkeypatch, pipeline):
    p = pipeline
    cancelled = False
    original_extractor = extract.MockExtractor()

    async def extraction(segments):
        nonlocal cancelled
        result = await original_extractor.extract(segments)
        cancelled = True
        return result

    async def fence(db, *args, **kwargs):
        if cancelled:
            raise steps.JobCancelled("Cancelled during extraction")
        await db.commit()

    monkeypatch.setattr(steps, "get_extractor", lambda: SimpleNamespace(extract=extraction))
    monkeypatch.setattr(steps, "guarded_commit", fence)
    with pytest.raises(steps.JobCancelled):
        await run(p)
    assert p.snapshots[-1][0] == ProcessingState.extracting
    assert p.snapshots[-1][2]["raw_transcript"]
    p.db.execute.assert_not_awaited()  # No action replacement or final result.
    p.db.rollback.assert_awaited_once()
    p.mail.assert_not_awaited()


@pytest.mark.parametrize("state", [ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent])
async def test_retry_after_final_commit_is_noop_preserving_human_work(pipeline, state):
    p = pipeline
    p.meeting.state = state
    p.meeting.transcript = "Human edited transcript"
    p.meeting.summary = "Human reviewed notes"
    await run(p)
    assert p.meeting.state == state and p.meeting.summary == "Human reviewed notes"
    p.download.assert_not_awaited()
    p.transcriber.transcribe.assert_not_awaited()
    p.db.commit.assert_not_awaited()
    p.mail.assert_not_awaited()


async def test_existing_plain_transcript_has_no_invented_audio_timestamps(pipeline):
    p = pipeline
    p.meeting.transcript = "An existing transcript without segment timestamps"
    await run(p)
    assert p.meeting.extracted_json["transcript_segments"] == []
    assert p.meeting.extracted_json["raw_transcript"] == p.meeting.transcript
    p.download.assert_not_awaited()


@pytest.mark.parametrize("attempts,expected", [(1, "pending"), (3, "failed")])
async def test_provider_exception_reaches_job_retry_or_failure(monkeypatch, pipeline, attempts, expected):
    p = pipeline
    monkeypatch.setattr(steps, "get_extractor", lambda: SimpleNamespace(extract=AsyncMock(side_effect=RuntimeError("AI unavailable"))))
    row = SimpleNamespace(id=uuid.uuid4(), drive_item_id="offline-item", drive_id="offline-drive",
                          owner_upn="owner@example.test", lease_token=uuid.uuid4(), status="processing",
                          attempts=attempts, max_attempts=3, cancel_requested_at=None)
    queue_db = MagicMock()
    queue_db.scalar = AsyncMock(return_value=row)
    queue_db.execute = AsyncMock()
    queue_db.commit = AsyncMock()
    queue_db.__aenter__ = AsyncMock(return_value=queue_db)
    queue_db.__aexit__ = AsyncMock(return_value=False)

    @asynccontextmanager
    async def unlocked(_):
        yield

    monkeypatch.setattr(worker, "SessionLocal", lambda: queue_db)
    monkeypatch.setattr(worker, "_recording_lock", unlocked)
    monkeypatch.setattr(worker, "_renew", AsyncMock(return_value=True))

    async def process(_):
        await run(p)

    monkeypatch.setattr(worker, "_process", process)
    await worker._execute(row)
    assert p.meeting.state == ProcessingState.failed and p.meeting.transcript
    assert row.status == expected and "failed" in row.last_error
    p.mail.assert_not_awaited()
