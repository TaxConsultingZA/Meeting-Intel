"""PostgreSQL-backed at-most-once submit reservation, fenced by the job lease.

A committed reservation can outlive a crashed process. It is intentionally not
replayed: without a provider idempotency key, exactly-once HTTP is impossible.
"""
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from ..config import get_settings
from sqlalchemy import select

from ..db import SessionLocal
from ..models import RecordingJob
from ..pipeline.transcribe import AssemblyAITranscriber, TranscriptSegment, ProviderTranscriptionError


async def checkpoint(job_id, lease_token, *, reserve=False, **values):
    async with SessionLocal() as db:
        job = await db.scalar(select(RecordingJob).where(
            RecordingJob.id == job_id, RecordingJob.lease_token == lease_token,
            RecordingJob.status == "processing", RecordingJob.cancel_requested_at.is_(None),
            RecordingJob.admission_version == 1,
            RecordingJob.authorized_at.is_not(None), RecordingJob.authorized_by.is_not(None),
            RecordingJob.locked_at >= datetime.now(timezone.utc) - timedelta(
                seconds=get_settings().worker_lease_seconds),
        ).with_for_update())
        if job is None:
            raise RuntimeError("Recording lease or processing authorization unavailable")
        if reserve:
            if job.submission_count != 0:
                raise RuntimeError("Provider submission requires manual reconciliation")
            job.submission_count = 1
            job.provider_status = "submitting"
        for key, value in values.items():
            setattr(job, key, value)
        await db.commit()


async def _drain_call(function, *args, stop=None):
    # Keep the recording/advisory lease until in-flight HTTP drains on shutdown.
    pending = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        if stop:
            stop.set()
        await asyncio.gather(pending, return_exceptions=True)
        raise


async def transcribe_recording(transcriber, path, job_id, lease_token):
    if not isinstance(transcriber, AssemblyAITranscriber):
        return await transcriber.transcribe(path)
    if not job_id or not lease_token:
        raise RuntimeError("Paid transcription requires a durable recording job")
    upload = await _drain_call(transcriber._upload, path)
    # Commit BEFORE making the only paid submit request. Commit uncertainty
    # itself prevents sending. Never infer that a timeout means 'not accepted'.
    await checkpoint(job_id, lease_token, reserve=True)
    try:
        provider_id = await _drain_call(transcriber._submit, upload)
    except BaseException:
        await checkpoint(job_id, lease_token, provider_status="submission_unknown")
        raise
    await checkpoint(job_id, lease_token, provider_transcript_id=provider_id,
                     provider_status="submitted")
    loop = asyncio.get_running_loop()
    last_status = None
    def observe(status):
        nonlocal last_status
        if status not in {"queued", "processing", "completed", "error"} or status == last_status:
            return
        asyncio.run_coroutine_threadsafe(checkpoint(job_id, lease_token,
            provider_status=status), loop).result(timeout=30)
        last_status = status
    transcriber.status_observer = observe
    try:
        stop = threading.Event()
        data = await _drain_call(transcriber._poll, provider_id, stop, stop=stop)
    except ProviderTranscriptionError:
        await checkpoint(job_id, lease_token, provider_status="error")
        raise
    except BaseException:
        await checkpoint(job_id, lease_token, provider_status="poll_unknown")
        raise
    await checkpoint(job_id, lease_token, provider_status="completed",
                     audio_duration_seconds=data.get("audio_duration"),
                     detected_language=data.get("language_code"))
    utterances = data.get("utterances") or []
    # Some supported languages return words/text without utterances. Preserve
    # original text with an unconfirmed voice label; never invent a person.
    if not utterances and data.get("text"):
        return [TranscriptSegment("Speaker A", data["text"], 0,
                                  float(data.get("audio_duration") or 0))]
    return [TranscriptSegment(f"Speaker {u['speaker']}", u["text"],
                              u["start"] / 1000, u["end"] / 1000) for u in utterances]
