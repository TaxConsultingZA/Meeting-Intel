"""Only the opt-in disposable loopback PostgreSQL fixture; no vendor/network calls."""
import asyncio
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from test_decisions import target, isolate_transports  # noqa: F401
from app.models import RecordingJob, RegisteredUser, Meeting
from app.queue import worker
from app.services import transcription_submission as submissions
from app.services.jobs import admission
from app.pipeline.transcribe import AssemblyAITranscriber, ProviderTranscriptionError
from app.api import recordings

OWNER = "synthetic-owner@example.test"


async def test_recording_filter_claim_and_recovery_exclude_other_admitted_jobs(database, monkeypatch):
    selected = await add_job(database)
    other = await add_job(database)
    expired_other = await add_job(database, status='processing', attempts=1,
        locked_at=worker._now()-timedelta(hours=1))
    monkeypatch.setattr(worker.settings, 'process_only_drive_id', selected.drive_id)
    monkeypatch.setattr(worker.settings, 'process_only_drive_item_id', selected.drive_item_id)
    assert (await worker._claim_next()).id == selected.id
    assert await worker._claim_next() is None
    await worker._recover_interrupted_jobs()
    async with database() as db:
        assert (await db.get(RecordingJob, other.id)).attempts == 0
        assert (await db.get(RecordingJob, expired_other.id)).status == 'processing'


async def test_partial_recording_filter_fails_closed(database, monkeypatch):
    row = await add_job(database)
    monkeypatch.setattr(worker.settings, 'process_only_drive_id', row.drive_id)
    monkeypatch.setattr(worker.settings, 'process_only_drive_item_id', '')
    assert await worker._claim_next() is None


async def child(target, row, operation, token=None):
    def run():
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('recording_process_probe.py'))],
            input=json.dumps({'url': target[0], 'job': str(row.id), 'token': str(token), 'operation': operation})+'\n',
            capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, 'Isolated child probe failed; sensitive output suppressed'
        return json.loads(result.stdout)
    return await asyncio.to_thread(run)


async def test_real_process_claim_restart_and_reservation(database, target):
    row = await add_job(database)
    claims = await asyncio.gather(child(target, row, 'claim'), child(target, row, 'claim'))
    assert sum(c['claimed'] for c in claims) == 1
    token = next(c['token'] for c in claims if c['claimed'])
    reservations = await asyncio.gather(child(target, row, 'reserve', token), child(target, row, 'reserve', token))
    assert sum(r['reserved'] for r in reservations) == 1
    # All children have exited. A new process has no memory of the reservation.
    assert not (await child(target, row, 'reserve', token))['reserved']
    async with database() as db:
        saved = await db.get(RecordingJob, row.id)
        saved.locked_at = worker._now() - timedelta(hours=1)
        await db.commit()
    await child(target, row, 'recover')
    assert not (await child(target, row, 'claim'))['claimed']
    async with database() as db:
        saved = await db.get(RecordingJob, row.id)
        assert (saved.status, saved.attempts, saved.submission_count, saved.provider_status) == ('failed', 1, 1, 'submission_unknown')


async def test_expired_reservation_and_stale_token_cannot_send(database, monkeypatch):
    row = await add_job(database)
    monkeypatch.setattr(worker.settings, 'process_only_job_id', str(row.id))
    row = await worker._claim_next()
    async with database() as db:
        saved = await db.get(RecordingJob, row.id)
        saved.locked_at = worker._now() - timedelta(hours=1)
        await db.commit()
    with pytest.raises(RuntimeError):
        await submissions.checkpoint(row.id, row.lease_token, reserve=True)


async def test_live_advisory_lock_then_killed_process_recovery(database, target, monkeypatch):
    row = await add_job(database)
    monkeypatch.setattr(worker.settings, 'process_only_job_id', str(row.id))
    row = await worker._claim_next()
    proc = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).with_name('recording_process_probe.py')),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        proc.stdin.write((json.dumps({'url':target[0], 'job':str(row.id), 'item':row.drive_item_id,'operation':'hold'})+'\n').encode())
        await proc.stdin.drain()
        ready = await asyncio.wait_for(proc.stdout.readline(), 20)
        assert json.loads(ready) == {'holding':True}
        async with database() as db:
            saved = await db.get(RecordingJob, row.id)
            saved.locked_at = worker._now() - timedelta(hours=1)
            await db.commit()
        await worker._recover_interrupted_jobs()
        async with database() as db:
            assert (await db.get(RecordingJob, row.id)).status == 'processing'
    finally:
        if proc.returncode is None:
            proc.kill()
        await asyncio.wait_for(proc.wait(), 20)
    await worker._recover_interrupted_jobs()
    async with database() as db:
        saved = await db.get(RecordingJob, row.id)
        assert (saved.status, saved.attempts, saved.submission_count) == ('failed',1,0)
    await worker._recover_interrupted_jobs()
    with pytest.raises(RuntimeError):
        await submissions.checkpoint(row.id, row.lease_token, reserve=True)


async def test_migration_round_trip_leaves_legacy_unadmitted(target):
    target[1]('downgrade', '51d8f2a7c903')
    engine = create_async_engine(target[0], connect_args={'ssl': False})
    old_id = uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO recording_jobs (id,drive_id,drive_item_id,owner_upn,source,status,attempts,max_attempts,available_at,created_at,updated_at) VALUES (:id,'synthetic-drive',:item,:owner,'manual','pending',0,3,now(),now(),now())"), {'id':old_id,'item':uuid4().hex,'owner':OWNER})
    target[1]('upgrade', 'head')
    async with engine.connect() as conn:
        row = (await conn.execute(text('SELECT admission_version,authorized_at,authorized_by,submission_count FROM recording_jobs WHERE id=:id'), {'id':old_id})).one()
        assert tuple(row) == (None, None, None, 0)
    target[1]('downgrade', '51d8f2a7c903')
    async with engine.connect() as conn:
        row = (await conn.execute(text('SELECT status,attempts FROM recording_jobs WHERE id=:id'), {'id':old_id})).one()
        assert tuple(row) == ('pending', 0)
        assert not await conn.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='recording_jobs' AND column_name='admission_version')"))
    target[1]('upgrade', 'head')
    await engine.dispose()


async def test_parallel_transcribers_only_one_http_submit(database, monkeypatch):
    row = await add_job(database)
    monkeypatch.setattr(worker.settings, 'process_only_job_id', str(row.id))
    row = await worker._claim_next()
    provider = AssemblyAITranscriber()
    provider._upload = Mock(return_value='synthetic-upload')
    provider._submit = Mock(return_value='synthetic-provider-id')
    provider._poll = Mock(return_value={'text':'合成中文原文', 'audio_duration':5, 'language_code':'zh'})
    results = await asyncio.gather(*(submissions.transcribe_recording(provider, 'synthetic.mp4', row.id, row.lease_token) for _ in range(2)), return_exceptions=True)
    assert provider._submit.call_count == 1
    assert sum(isinstance(result, RuntimeError) for result in results) == 1
    assert next(r for r in results if isinstance(r, list))[0].text == '合成中文原文'


async def test_unresolved_submission_cannot_be_bypassed_by_new_retry(database):
    from app.services.jobs import enqueue_retry_job
    old = await add_job(database, status='failed', submission_count=1, provider_status='submission_unknown')
    async with database() as db:
        assert not await enqueue_retry_job(db, drive_item_id=old.drive_item_id, drive_id=old.drive_id,
            owner_upn=OWNER, authorized_by=OWNER)


async def test_regular_worker_stays_enabled_and_processes_next_job(database, monkeypatch):
    old = await add_job(database, admitted=False)
    first, second = await add_job(database), await add_job(database)
    stop = asyncio.Event()
    processed = []
    async def process(row):
        processed.append(row.id)
        if len(processed) == 2:
            stop.set()
    monkeypatch.setattr(worker, '_process', process)
    await asyncio.wait_for(worker.run_worker(stop), 10)
    assert processed == [first.id, second.id]
    assert worker.settings.recording_processing_enabled is True
    async with database() as db:
        assert (await db.get(RecordingJob, first.id)).status == 'completed'
        assert (await db.get(RecordingJob, second.id)).status == 'completed'
        assert (await db.get(RecordingJob, old.id)).attempts == 0


async def test_commit_acknowledgement_loss_never_sends(database, monkeypatch):
    row = await add_job(database)
    monkeypatch.setattr(worker.settings, 'process_only_job_id', str(row.id))
    row = await worker._claim_next()
    checkpoint = submissions.checkpoint
    async def lost_ack(*args, **kwargs):
        await checkpoint(*args, **kwargs)
        raise ConnectionError('Synthetic commit acknowledgement lost')
    monkeypatch.setattr(submissions, 'checkpoint', lost_ack)
    provider = AssemblyAITranscriber()
    provider._upload = Mock(return_value='synthetic-upload')
    provider._submit = Mock(return_value='synthetic-id')
    with pytest.raises(ConnectionError):
        await submissions.transcribe_recording(provider, 'synthetic.mp4', row.id, row.lease_token)
    provider._submit.assert_not_called()
    await worker._finish(row.id, row.lease_token, RuntimeError('Synthetic interrupted commit'))
    async with database() as db:
        saved = await db.get(RecordingJob, row.id)
        assert (saved.submission_count, saved.provider_status, saved.status) == (1,'submission_unknown','failed')


@pytest.fixture
async def database(target, monkeypatch):
    target[1]("upgrade", "head")
    engine = create_async_engine(target[0], connect_args={"ssl": False})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(submissions, "SessionLocal", sessions)
    monkeypatch.setattr(worker.settings, "recording_processing_enabled", True)
    monkeypatch.setattr(worker.settings, "process_only_job_id", "")
    monkeypatch.setattr(worker.settings, "emails_enabled", False)
    monkeypatch.setattr(worker.settings, "popia_notice_enabled", False)
    yield sessions
    await engine.dispose()


async def add_job(database, admitted=True, **kwargs):
    async with database() as db:
        row = RecordingJob(drive_id="synthetic-drive", drive_item_id=uuid4().hex,
                           owner_upn=OWNER, source="manual", **(admission(OWNER) if admitted else {}), **kwargs)
        db.add(row)
        await db.commit()
        return row


async def test_concurrent_claim_and_recovery_never_touch_legacy(database, monkeypatch):
    old = await add_job(database, admitted=False)
    expired_old = await add_job(database, admitted=False, status="processing", attempts=1,
                                locked_at=worker._now() - timedelta(hours=1))
    fresh = await add_job(database)
    monkeypatch.setattr(worker.settings, "process_only_job_id", str(fresh.id))
    claims = await asyncio.gather(*(worker._claim_next() for _ in range(5)))
    assert sum(row is not None for row in claims) == 1
    async with database() as db:
        row = await db.get(RecordingJob, fresh.id)
        row.locked_at = worker._now() - timedelta(hours=1)
        row.submission_count = 1
        row.provider_status = "submitting"
        await db.commit()
    # A new SessionLocal invocation simulates a worker with no in-memory state.
    await worker._recover_interrupted_jobs()
    assert await worker._claim_next() is None
    monkeypatch.setattr(worker.settings, "process_only_job_id", "")
    await worker._recover_interrupted_jobs()
    async with database() as db:
        assert (await db.get(RecordingJob, old.id)).attempts == 0
        assert (await db.get(RecordingJob, expired_old.id)).status == "processing"
        row = await db.get(RecordingJob, fresh.id)
        assert (row.status, row.attempts, row.provider_status) == ("failed", 1, "submission_unknown")


@pytest.mark.parametrize("outcome", ["completed", "submit_timeout", "provider_error", "poll_timeout"])
async def test_durable_submit_fences_failures_and_preserves_language(database, monkeypatch, outcome):
    row = await add_job(database)
    monkeypatch.setattr(worker.settings, "process_only_job_id", str(row.id))
    row = await worker._claim_next()
    transcriber = AssemblyAITranscriber()
    transcriber._upload = Mock(return_value="synthetic-upload")
    transcriber._submit = Mock(return_value="synthetic-provider-id")
    transcriber._poll = Mock(return_value={"audio_duration": 12, "language_code": "zh",
        "utterances": [{"speaker": "A", "text": "合成中文，不翻译。", "start": 1000, "end": 12000}]})
    if outcome == "submit_timeout":
        transcriber._submit.side_effect = TimeoutError("synthetic timeout")
    elif outcome == "provider_error":
        transcriber._poll.side_effect = ProviderTranscriptionError("synthetic error")
    elif outcome == "poll_timeout":
        transcriber._poll.side_effect = TimeoutError("synthetic poll timeout")
    error = None
    try:
        segments = await submissions.transcribe_recording(transcriber, "synthetic.mp4", row.id, row.lease_token)
    except Exception as exc:
        error = exc
    if outcome == "completed":
        assert error is None
        assert segments[0].text == "合成中文，不翻译。"
        assert segments[0].speaker == "Speaker A"
    else:
        assert isinstance(error, ProviderTranscriptionError if outcome == "provider_error" else TimeoutError)
    await worker._finish(row.id, row.lease_token, error)
    assert transcriber._submit.call_count == 1
    async with database() as db:
        saved = await db.get(RecordingJob, row.id)
        assert saved.submission_count == 1
        assert saved.provider_status == {"completed": "completed", "submit_timeout": "submission_unknown",
            "provider_error": "error", "poll_timeout": "poll_unknown"}[outcome]
        if outcome == "completed":
            assert saved.status == "completed"
            assert saved.detected_language == "zh" and saved.audio_duration_seconds == 12
        else:
            assert saved.status == "failed"
    assert await worker._claim_next() is None


async def test_concurrent_reservation_allows_only_one_sender(database, monkeypatch):
    row = await add_job(database)
    monkeypatch.setattr(worker.settings, "process_only_job_id", str(row.id))
    row = await worker._claim_next()
    outcomes = await asyncio.gather(*(submissions.checkpoint(row.id, row.lease_token, reserve=True)
                                      for _ in range(5)), return_exceptions=True)
    assert sum(result is None for result in outcomes) == 1
    assert sum(isinstance(result, RuntimeError) for result in outcomes) == 4
    # Even a crash before HTTP after reservation cannot send again.
    with pytest.raises(RuntimeError, match="reconciliation"):
        await submissions.checkpoint(row.id, row.lease_token, reserve=True)


async def test_click_concurrency_to_saved_meeting(database, monkeypatch):
    from app.pipeline import steps
    from app.graph import client as graph
    from app.pipeline.transcribe import MockTranscriber
    from app.pipeline.extract import TranscriptOnlyExtractor
    from app.services import job_control
    monkeypatch.setattr(job_control, "SessionLocal", database, raising=False)
    async with database() as db:
        user = RegisteredUser(upn=OWNER, display_name="Synthetic owner", is_subscribed=True)
        db.add(user)
        await db.commit()
    item = uuid4().hex
    monkeypatch.setattr(recordings, "_verify_owned_drive_item", AsyncMock(return_value={"id": item, "name": "合成测试.mp4"}))
    async def click():
        async with database() as db:
            try:
                return await recordings.import_recording(recordings.ImportRequest(drive_id="synthetic-drive", drive_item_id=item), db, OWNER)
            except HTTPException as exc:
                return exc.status_code
    clicks = await asyncio.gather(click(), click(), click())
    assert sum(isinstance(value, dict) for value in clicks) == 1
    async with database() as db:
        rows = list(await db.scalars(select(RecordingJob).where(RecordingJob.drive_item_id == item)))
        assert len(rows) == 1 and rows[0].admission_version == 1
        target_id = rows[0].id
    monkeypatch.setattr(worker.settings, "process_only_job_id", str(target_id))
    monkeypatch.setattr(graph, "get_drive_item", AsyncMock(return_value={"id": item, "name": "合成测试.mp4"}))
    monkeypatch.setattr(graph, "get_event_attendees", AsyncMock(return_value=[]))
    async def download(drive, item, dest):
        Path(dest).write_bytes(b"synthetic-media")
    monkeypatch.setattr(graph, "download_drive_item", download)
    monkeypatch.setattr(graph, "send_mail", AsyncMock(side_effect=AssertionError("No mail")))
    monkeypatch.setattr(steps.settings, "graph_impl", "mock")
    monkeypatch.setattr(steps, "get_transcriber", lambda: MockTranscriber())
    monkeypatch.setattr(steps.settings, "extractor_impl", "transcript_only")
    assert await worker.run_worker_once()
    async with database() as db:
        saved = await db.get(RecordingJob, target_id)
        meeting = await db.scalar(select(Meeting).where(Meeting.drive_item_id == item))
        assert saved.status == "completed" and saved.attempts == 1
        assert meeting.state.value == "awaiting_review" and meeting.transcript
        assert meeting.extracted_json["extraction_mode"] == "transcript_only"
    assert not await worker.run_worker_once()
