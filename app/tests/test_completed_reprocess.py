import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import recordings
from app.models import AuditEvent, ProcessingState
from app.pipeline import extract, steps
from app.ai import runtime_bridge
from app.ai.providers import ProviderIdentity
from app.ai.processing import ProcessingCancelled
from app.pipeline.transcribe import TranscriptSegment
from app.services.reprocessing import (
    MANUAL_REPROCESS_SOURCE,
    is_clean_reprocess_candidate,
    result_fingerprint,
)


def clean_meeting(state=ProcessingState.awaiting_review):
    return SimpleNamespace(
        id=uuid4(), drive_item_id="item", organizer_upn="owner@example.test",
        state=state, transcript="old transcript", summary="old summary",
        extracted_json={"raw_transcript": "old transcript", "outlook_event_id": "event"},
        action_items=[], participants=[SimpleNamespace(
            user_upn="owner@example.test", is_organizer=True,
        )],
        attendees_raw=["owner@example.test"], recorded_at=None, error=None,
        approved_recipients=None, approved_by=None,
        approved_at=None, email_delivery_status=None, email_delivery_fingerprint=None,
    )


def fake_db(*scalar_results):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=scalar_results)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    return db


async def test_clean_awaiting_review_reprocess_queues_distinct_job(monkeypatch):
    meeting = clean_meeting()
    ledger = SimpleNamespace(drive_id="drive")
    db = fake_db(meeting, ledger, uuid4())
    verify = AsyncMock()
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(recordings, "_verify_owned_drive_item", verify)
    monkeypatch.setattr(recordings, "enqueue_retry_job", enqueue)

    result = await recordings.reprocess_recording(
        recordings.ImportRequest(drive_item_id="item", drive_id="untrusted"),
        db,
        SimpleNamespace(id=uuid4(), upn="owner@example.test", is_subscribed=True),
    )

    assert result == {"ok": True, "queued": True}
    assert meeting.state == ProcessingState.awaiting_review
    assert meeting.transcript == "old transcript"
    verify.assert_awaited_once_with("owner@example.test", "drive", "item")
    assert enqueue.await_args.kwargs["source"] == MANUAL_REPROCESS_SOURCE


def test_edited_awaiting_review_is_not_clean():
    meeting = clean_meeting()
    meeting.transcript = "human edit"
    assert not is_clean_reprocess_candidate(meeting)


async def test_edited_awaiting_review_reprocess_is_rejected():
    meeting = clean_meeting()
    meeting.transcript = "human edit"
    with pytest.raises(HTTPException) as exc:
        await recordings.reprocess_recording(
            recordings.ImportRequest(drive_item_id="item", drive_id="drive"),
            fake_db(meeting),
            "owner@example.test",
        )
    assert exc.value.status_code == 409


@pytest.mark.parametrize("state", [ProcessingState.approved, ProcessingState.sent])
async def test_approved_and_sent_reprocess_are_rejected(state):
    with pytest.raises(HTTPException) as exc:
        await recordings.reprocess_recording(
            recordings.ImportRequest(drive_item_id="item", drive_id="drive"),
            fake_db(clean_meeting(state)),
            "owner@example.test",
        )
    assert exc.value.status_code == 409


@pytest.mark.parametrize("failure", [RuntimeError("provider failed"), steps.JobCancelled("cancelled")])
async def test_reprocess_failure_or_cancel_keeps_old_result(monkeypatch, failure):
    meeting = clean_meeting()
    before = (meeting.state, meeting.transcript, meeting.summary, deepcopy(meeting.extracted_json))
    db = fake_db()
    monkeypatch.setattr(steps.graph, "download_drive_item", AsyncMock())
    monkeypatch.setattr(steps, "get_transcriber", lambda: SimpleNamespace(
        transcribe=AsyncMock(side_effect=failure)
    ))
    commit_result = AsyncMock()
    monkeypatch.setattr(steps, "_commit_reprocess_result", commit_result)

    with pytest.raises(type(failure)):
        await steps._reprocess_completed_recording(
            db, meeting, "item", "drive", job_id=uuid4(), lease_token=uuid4()
        )

    assert (meeting.state, meeting.transcript, meeting.summary, meeting.extracted_json) == before
    commit_result.assert_not_awaited()


@pytest.mark.parametrize("failure", ["failed", "invalid", "cancelled"])
async def test_foundation_reprocess_failure_preserves_previous_success(monkeypatch, failure):
    meeting = clean_meeting()
    previous_action = SimpleNamespace(task="Keep reviewed action", approved=False)
    meeting.action_items = [previous_action]
    before = (meeting.state, meeting.transcript, meeting.summary, deepcopy(meeting.extracted_json))
    db = fake_db()
    monkeypatch.setattr(steps.graph, "download_drive_item", AsyncMock())
    monkeypatch.setattr(steps, "get_transcriber", lambda: SimpleNamespace(
        transcribe=AsyncMock(return_value=[TranscriptSegment("Speaker A", "Fresh words", 0, 1)])))
    provider = SimpleNamespace(identity=ProviderIdentity("test.local"), process=AsyncMock(
        return_value={"summary": "invalid"},
        side_effect=(RuntimeError("failure") if failure == "failed" else
                     asyncio.CancelledError() if failure == "cancelled" else None)))
    monkeypatch.setattr(runtime_bridge, "get_local_provider", lambda _: provider)
    install = AsyncMock()
    notify = AsyncMock()
    monkeypatch.setattr(steps, "_commit_reprocess_result", install)
    monkeypatch.setattr(steps, "_send_ready_for_review", notify)
    expected = ProcessingCancelled if failure == "cancelled" else runtime_bridge.FoundationExtractionError
    with pytest.raises(expected):
        await steps._reprocess_completed_recording(
            db, meeting, "item", "drive", job_id=uuid4(), lease_token=uuid4())
    assert (meeting.state, meeting.transcript, meeting.summary, meeting.extracted_json) == before
    assert meeting.action_items == [previous_action]
    install.assert_not_awaited()
    db.execute.assert_not_awaited()
    notify.assert_not_awaited()


async def test_reprocess_uses_fresh_transcription_instead_of_old_transcript(monkeypatch):
    meeting = clean_meeting()
    db = fake_db()
    segments = [TranscriptSegment("Speaker A", "fresh words", 0, 1)]
    transcribe = AsyncMock(return_value=segments)
    commit_result = AsyncMock(return_value=meeting)
    monkeypatch.setattr(steps.graph, "download_drive_item", AsyncMock())
    monkeypatch.setattr(steps, "get_transcriber", lambda: SimpleNamespace(transcribe=transcribe))
    monkeypatch.setattr(steps, "_commit_reprocess_result", commit_result)
    monkeypatch.setattr(steps, "_send_ready_for_review", AsyncMock())

    await steps._reprocess_completed_recording(
        db, meeting, "item", "drive", job_id=uuid4(), lease_token=uuid4()
    )

    transcribe.assert_awaited_once()
    assert commit_result.await_args.kwargs["transcript"] == "[Speaker A] fresh words"
    assert commit_result.await_args.kwargs["transcript"] != "old transcript"


async def test_manual_reprocess_job_dispatches_to_safe_pipeline_branch(monkeypatch):
    meeting = clean_meeting()
    job = SimpleNamespace(source=MANUAL_REPROCESS_SOURCE)
    db = fake_db(job, meeting)
    monkeypatch.setattr(steps, "guarded_commit", AsyncMock())
    reprocess = AsyncMock()
    monkeypatch.setattr(steps, "_reprocess_completed_recording", reprocess)
    job_id = uuid4()
    lease_token = uuid4()

    await steps.process_recording(
        db, "item", "drive", owner_upn="owner@example.test",
        job_id=job_id, lease_token=lease_token,
    )

    reprocess.assert_awaited_once_with(
        db, meeting, "item", "drive", job_id=job_id, lease_token=lease_token
    )


async def test_reprocess_always_transcribes_and_success_replaces_atomically(monkeypatch):
    meeting = clean_meeting()
    job = SimpleNamespace(id=uuid4(), attempts=1, source=MANUAL_REPROCESS_SOURCE, status="processing", lease_token=uuid4(), locked_at=object(), last_error=None)
    baseline = result_fingerprint(meeting)
    db = fake_db(job, meeting)
    result = await extract.MockExtractor().extract([
        TranscriptSegment("Speaker A", "new words", 0, 1)
    ])
    new_json = {"raw_transcript": "[Speaker A] new words", "fresh": True}

    updated = await steps._commit_reprocess_result(
        db,
        job_id=uuid4(),
        lease_token=job.lease_token,
        meeting_id=meeting.id,
        baseline_fingerprint=baseline,
        transcript="[Speaker A] new words",
        extracted_json=new_json,
        result=result,
    )

    assert updated.transcript == "[Speaker A] new words"
    assert updated.summary == result.summary
    assert updated.extracted_json == new_json
    assert updated.state == ProcessingState.awaiting_review
    assert job.status == "completed" and job.lease_token is None
    audit_events = [call.args[0] for call in db.add.call_args_list
                    if isinstance(call.args[0], AuditEvent)]
    assert len(audit_events) == 1
    assert audit_events[0].outcome == "succeeded"
    assert audit_events[0].meeting_id == meeting.id
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


async def test_edit_during_reprocess_is_not_overwritten():
    meeting = clean_meeting()
    baseline = result_fingerprint(meeting)
    meeting.transcript = "human edit during processing"
    job = SimpleNamespace(id=uuid4(), attempts=1, source=MANUAL_REPROCESS_SOURCE, status="processing", lease_token=uuid4(), locked_at=object(), last_error=None)
    db = fake_db(job, meeting)
    result = await extract.MockExtractor().extract([
        TranscriptSegment("Speaker A", "new words", 0, 1)
    ])

    with pytest.raises(steps.ReprocessConflict):
        await steps._commit_reprocess_result(
            db,
            job_id=uuid4(),
            lease_token=job.lease_token,
            meeting_id=meeting.id,
            baseline_fingerprint=baseline,
            transcript="machine replacement",
            extracted_json={"raw_transcript": "machine replacement"},
            result=result,
        )

    assert meeting.transcript == "human edit during processing"
    assert meeting.summary == "old summary"
    assert job.status == "failed" and "reprocess conflict" in job.last_error
    event = db.add.call_args.args[0]
    assert isinstance(event, AuditEvent) and event.outcome == "failed"
    assert event.event_metadata["error_category"] == "reprocess_conflict"
    db.execute.assert_not_awaited()
