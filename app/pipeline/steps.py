import os
import tempfile

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..models import Meeting, ActionItem, MeetingParticipant, ProcessingState, RecordingJob, RegisteredUser
from ..graph import client as graph
from ..utils.identity import normalize_upn, normalize_upns
from .transcribe import get_transcriber, TranscriptSegment
from .extract import get_extractor, require_transcript, validate_extraction
from ..services.job_control import guarded_commit, JobCancelled, public_job_error
from ..services.reprocessing import (
    MANUAL_REPROCESS_SOURCE,
    is_clean_reprocess_candidate,
    result_fingerprint,
)

settings = get_settings()


class ReprocessConflict(Exception):
    """A completed result changed before its safe replacement could commit."""


async def _stop_reprocess_conflict(db, job_id, lease_token, detail: str) -> None:
    """End a conflicted reprocess without letting normal retry overwrite user work."""
    job = await db.scalar(select(RecordingJob).where(
        RecordingJob.id == job_id,
        RecordingJob.status == "processing",
        RecordingJob.lease_token == lease_token,
    ).with_for_update())
    if job is None:
        await db.rollback()
        raise JobCancelled("Cancellation requested or recording lease lost")
    job.status = "failed"
    job.locked_at = None
    job.lease_token = None
    job.last_error = f"reprocess conflict: {detail}"
    await db.commit()
    raise ReprocessConflict(job.last_error)


async def _commit_reprocess_result(
    db, *, job_id, lease_token, meeting_id, baseline_fingerprint,
    transcript, extracted_json, result,
) -> Meeting:
    """Fence the job, recheck the old draft, and atomically install new output."""
    job = await db.scalar(select(RecordingJob).where(
        RecordingJob.id == job_id,
        RecordingJob.status == "processing",
        RecordingJob.lease_token == lease_token,
        RecordingJob.cancel_requested_at.is_(None),
    ).with_for_update().execution_options(populate_existing=True))
    if job is None:
        await db.rollback()
        raise JobCancelled("Cancellation requested or recording lease lost")

    meeting = await db.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(selectinload(Meeting.action_items))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        meeting is None
        or not is_clean_reprocess_candidate(meeting)
        or result_fingerprint(meeting) != baseline_fingerprint
    ):
        job.status = "failed"
        job.locked_at = None
        job.lease_token = None
        job.last_error = "reprocess conflict: meeting results changed during processing"
        await db.commit()
        raise ReprocessConflict(job.last_error)

    meeting.transcript = transcript
    meeting.summary = result.summary
    meeting.extracted_json = extracted_json
    meeting.error = None
    meeting.state = ProcessingState.awaiting_review
    await db.execute(delete(ActionItem).where(ActionItem.meeting_id == meeting.id))
    for ai in result.action_items:
        db.add(ActionItem(
            meeting_id=meeting.id,
            task=ai.action or ai.task,
            owner=ai.assigned_to or ai.owner,
            deadline_text=ai.due_date or ai.deadline_text,
            deadline_iso=ai.deadline_iso,
            confidence=ai.confidence,
            source_quote=ai.source_quote,
            raw=ai.model_dump(),
            approved=False,
        ))
    job.status = "completed"
    job.last_error = None
    job.locked_at = None
    job.lease_token = None
    await db.commit()
    return meeting


async def _reprocess_completed_recording(
    db, meeting, drive_item_id, drive_id, *, job_id, lease_token,
) -> None:
    """Generate a fresh result off-row, retaining the current successful draft."""
    if not is_clean_reprocess_candidate(meeting):
        await _stop_reprocess_conflict(
            db, job_id, lease_token, "meeting results are edited or no longer awaiting review"
        )
    baseline_fingerprint = result_fingerprint(meeting)
    preserved_extracted = dict(meeting.extracted_json or {})
    participant_count = len(meeting.participants or [])
    meeting_id = meeting.id
    recorded_at = meeting.recorded_at
    await db.commit()  # Release the read transaction before external processing.

    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "rec.mp4")
        await graph.download_drive_item(drive_id, drive_item_id, video_path)
        segments = await get_transcriber().transcribe(video_path)
        require_transcript(segments)
        transcript = "\n".join(f"[{segment.speaker}] {segment.text}" for segment in segments)
        result = validate_extraction(
            await get_extractor().extract(segments),
            transcript_only=settings.extractor_impl == "transcript_only",
        )

    extracted_json = preserved_extracted
    extracted_json.pop("speaker_mappings", None)
    extracted_json.update(result.model_dump())
    extracted_json["raw_transcript"] = transcript
    extracted_json["transcript_segments"] = [
        {"speaker": segment.speaker, "text": segment.text,
         "start": segment.start, "end": segment.end}
        for segment in segments
    ]
    if recorded_at:
        extracted_json["meeting_time"] = recorded_at.isoformat()

    meeting = await _commit_reprocess_result(
        db,
        job_id=job_id,
        lease_token=lease_token,
        meeting_id=meeting_id,
        baseline_fingerprint=baseline_fingerprint,
        transcript=transcript,
        extracted_json=extracted_json,
        result=result,
    )
    await _send_ready_for_review(meeting, participant_count)

_PROCESSING_STARTED_HTML = """
<html><body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:600px;margin:0 auto;">
  <div style="background:#003366;border-bottom:4px solid #C9A52C;padding:24px 32px;">
    <h1 style="color:white;margin:0;font-size:20px;">TaxConsulting SA</h1>
    <p style="color:rgba(255,255,255,0.65);margin:4px 0 0;font-size:13px;">Meeting Intelligence</p>
  </div>
  <div style="padding:32px;">
    <h2 style="color:#003366;font-size:18px;margin-top:0;">Meeting Recording Is Being Processed</h2>
    <p style="font-size:14px;line-height:1.7;">The recording for <strong>{title}</strong> has been detected and is now being transcribed and analysed by our AI system.</p>
    <div style="background:#f0f4ff;border:1px solid #c7d2fe;border-radius:8px;padding:16px 20px;margin:20px 0;">
      <p style="margin:0;font-size:13px;color:#6b7280;">Estimated completion time</p>
      <p style="margin:4px 0 0;font-size:22px;font-weight:700;color:#003366;">~15–20 minutes</p>
    </div>
    <p style="font-size:13px;color:#6b7280;">You will receive another email once the meeting notes are ready for your review and approval.</p>
  </div>
  <div style="background:#f8fafc;border-top:1px solid #dde1e8;padding:14px 32px;font-size:11px;color:#9ca3af;">
    Taxconsulting SA (Pty) Ltd &middot; Meeting Intelligence Platform
  </div>
</body></html>
"""

_READY_FOR_REVIEW_HTML = """
<html><body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:600px;margin:0 auto;">
  <div style="background:#003366;border-bottom:4px solid #C9A52C;padding:24px 32px;">
    <h1 style="color:white;margin:0;font-size:20px;">TaxConsulting SA</h1>
    <p style="color:rgba(255,255,255,0.65);margin:4px 0 0;font-size:13px;">Meeting Intelligence</p>
  </div>
  <div style="padding:32px;">
    <h2 style="color:#003366;font-size:18px;margin-top:0;">Meeting Notes Ready for Review</h2>
    <p style="font-size:14px;line-height:1.7;">The AI-extracted meeting notes for <strong>{title}</strong> are now ready for your review and approval.</p>
    <a href="{app_url}/meetings/{meeting_id}" style="display:inline-block;background:#C9A52C;color:#003366;font-weight:700;font-size:14px;padding:12px 24px;border-radius:6px;text-decoration:none;margin:8px 0;">Review &amp; Approve Meeting Notes &rarr;</a>
    <p style="font-size:13px;color:#6b7280;margin-top:20px;">Once approved, the formatted notes will be emailed to all <strong>{participant_count}</strong> meeting participants.</p>
  </div>
  <div style="background:#f8fafc;border-top:1px solid #dde1e8;padding:14px 32px;font-size:11px;color:#9ca3af;">
    Taxconsulting SA (Pty) Ltd &middot; Meeting Intelligence Platform
  </div>
</body></html>
"""

_POPIA_NOTICE_HTML = """
<p>Dear Participant,</p>

<p>This is an automated notice from <strong>Taxconsulting SA (Pty) Ltd</strong> in compliance
with the <strong>Protection of Personal Information Act, 2013 (POPIA)</strong>.</p>

<p>A Microsoft Teams recording titled <strong>{title}</strong> has been detected in your
organisation's SharePoint library and is being processed by our Meeting Intelligence system.
The following AI-assisted steps will be performed:</p>

<ul>
  <li><strong>Transcription</strong> — the audio is converted to a diarized text transcript.</li>
  <li><strong>Action-item extraction</strong> — a language model identifies tasks, owners,
      and deadlines mentioned during the meeting.</li>
</ul>

<p><strong>Who can see the results?</strong><br>
Access is limited to confirmed participants of this meeting only.
No output is shared more widely or emailed to anyone until the meeting organiser explicitly
reviews and approves it.</p>

<p><strong>Data retention</strong><br>
Transcripts and extracted action items are retained in a private database.
A blob-retention and auto-deletion policy is being finalised; you will be notified
once it is in place.</p>

<p><strong>Your rights under POPIA</strong><br>
You have the right to request access to, correction of, or deletion of your personal
information. To exercise these rights or to object to the processing of your information,
please contact the Information Officer at
<a href="mailto:privacy@taxconsulting.co.za">privacy@taxconsulting.co.za</a>.</p>

<p>If you believe this recording was made without proper consent, please notify the
Information Officer immediately and processing will be suspended pending review.</p>

<p>Kind regards,<br>
<em>Taxconsulting SA Meeting Intelligence — automated notice</em></p>
"""


async def _send_notification(sender: str, recipients: list[str], subject: str, html: str) -> None:
    """Fire-and-forget email — swallow errors so a mail failure never kills the pipeline."""
    if not settings.emails_enabled:
        return
    try:
        await graph.send_mail(sender, recipients, subject, html)
    except Exception:
        pass


async def _send_processing_started(meeting: Meeting, all_upns: list[str]) -> None:
    """Email all known participants that transcription has started and give a time estimate.

    Sent from the organiser's mailbox to all UPNs gathered so far (organiser +
    any attendees found in SharePoint metadata).  Silently skipped if no
    organiser UPN is known.
    """
    if not meeting.organizer_upn:
        return
    title = meeting.title or "a recent Teams meeting"
    html = _PROCESSING_STARTED_HTML.format(title=title)
    await _send_notification(
        meeting.organizer_upn,
        list(set(all_upns)),
        f"Processing started — {title}",
        html,
    )


async def _send_ready_for_review(meeting: Meeting, participant_count: int) -> None:
    """Email the organiser that the AI-extracted notes are ready for their review.

    Includes a direct deep-link to the meeting detail page.  Only sent to the
    organiser — participants receive the full notes email only after approval.
    """
    if not meeting.organizer_upn:
        return
    title = meeting.title or "a recent Teams meeting"
    html = _READY_FOR_REVIEW_HTML.format(
        title=title,
        app_url=settings.app_url.rstrip("/"),
        meeting_id=str(meeting.id),
        participant_count=participant_count,
    )
    await _send_notification(
        meeting.organizer_upn,
        [meeting.organizer_upn],
        f"Meeting notes ready for review — {title}",
        html,
    )


async def _send_popia_notice(meeting: Meeting, extra_recipients: list[str]) -> None:
    if not settings.emails_enabled or not settings.popia_notice_enabled or not meeting.organizer_upn:
        return
    recipients = list({meeting.organizer_upn, *extra_recipients} - {None})
    if not recipients:
        return
    title = meeting.title or "a recent Teams meeting"
    await graph.send_mail(
        meeting.organizer_upn,
        recipients,
        f"[Action required] AI processing notice — {title}",
        _POPIA_NOTICE_HTML.format(title=title),
    )


async def process_recording(
    db: AsyncSession, drive_item_id: str, drive_id: str, owner_upn: str | None = None,
    *, job_id=None, lease_token=None,
) -> None:
    """Run the full pipeline for a single recording and persist the results.

    Steps:
        1. Create (or reuse) the Meeting row — state starts at ``queued``.
        2. Add ``owner_upn`` as a participant immediately so the meeting is
           visible in the dashboard during processing.
        3. Send the POPIA processing notice to known participants.
        4. Download the MP4 from OneDrive (streams to a temp file).
        5. Transcribe via AssemblyAI (diarized speaker labels).
        6. Email participants: "transcription started, ~15-20 min ETA".
        7. Run the configured extractor (transcript-only until an AI is selected).
        8. Persist any structured results and all participant UPNs.
        9. Set state to ``awaiting_review`` and email the organiser.

    Any unhandled exception sets state to ``failed`` and re-raises.
    """
    async def commit(*, complete=False):
        await guarded_commit(db, job_id, lease_token, complete=complete)

    is_reprocess = False
    if job_id is not None:
        await commit()
        current_job = await db.scalar(select(RecordingJob).where(RecordingJob.id == job_id))
        is_reprocess = getattr(current_job, "source", None) == MANUAL_REPROCESS_SOURCE
    meeting_query = select(Meeting).where(Meeting.drive_item_id == drive_item_id)
    if is_reprocess:
        meeting_query = meeting_query.options(
            selectinload(Meeting.action_items), selectinload(Meeting.participants)
        )
    meeting = await db.scalar(meeting_query)
    if is_reprocess:
        if meeting is None:
            await _stop_reprocess_conflict(
                db, job_id, lease_token, "the original completed meeting is unavailable"
            )
        await _reprocess_completed_recording(
            db, meeting, drive_item_id, drive_id, job_id=job_id, lease_token=lease_token
        )
        return
    if meeting is not None and meeting.state in (
        ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent,
    ):
        # A crash after the final DB commit must not overwrite human review or
        # repeat processing/notifications on the next job attempt.
        return
    if meeting is None:
        meta = await graph.get_drive_item(drive_id, drive_item_id)
        user_node = (meta.get("createdBy", {}).get("user", {}) or {})
        organizer = normalize_upn(
            user_node.get("userPrincipalName")
            or user_node.get("email")
            or owner_upn          # fallback: whoever's drive this file lives in
        )
        meeting = Meeting(
            drive_item_id=drive_item_id,
            title=meta.get("name"),
            organizer_upn=organizer,
        )
        db.add(meeting)
        await commit()
        await db.refresh(meeting)

    owner_upn = normalize_upn(owner_upn)
    if meeting.organizer_upn:
        meeting.organizer_upn = normalize_upn(meeting.organizer_upn)

    # Add owner as participant immediately so the meeting shows in the dashboard
    # during processing (participant rows are the visibility gate for /reviews/all).
    if owner_upn:
        already = await db.scalar(
            select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.user_upn == owner_upn,
            )
        )
        if not already:
            db.add(MeetingParticipant(
                meeting_id=meeting.id,
                user_upn=owner_upn,
                is_organizer=(owner_upn == meeting.organizer_upn),
            ))
            await commit()

    # Notify participants before any AI processing (POPIA Section 18).
    extra = normalize_upns(meeting.attendees_raw if meeting.attendees_raw is not None
                           else await graph.get_event_attendees(drive_id, drive_item_id))

    # Persist the full attendee list so historical-access requests can be verified later,
    # even after the pipeline filters participants down to registered users only.
    all_attendee_upns = normalize_upns([*extra, meeting.organizer_upn, owner_upn])
    if meeting.attendees_raw is None:
        meeting.attendees_raw = all_attendee_upns
        await commit()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            meeting.error = None
            transcript_segments = (meeting.extracted_json or {}).get("transcript_segments") or []
            if meeting.transcript and meeting.transcript.strip():
                # AI-only retries reuse durable transcription, avoiding another
                # download/transcription charge. Never manufacture audio times.
                segments = ([TranscriptSegment(**s) for s in transcript_segments]
                            if transcript_segments else
                            [TranscriptSegment("Transcript", meeting.transcript, 0, 0)])
            else:
                await _send_popia_notice(meeting, extra)
                meeting.state = ProcessingState.downloading
                await commit()
                video_path = os.path.join(tmp, "rec.mp4")
                await graph.download_drive_item(drive_id, drive_item_id, video_path)
                meeting.state = ProcessingState.transcribing
                await commit()
                all_upns = normalize_upns([*extra, meeting.organizer_upn, owner_upn])
                await _send_processing_started(meeting, all_upns)
                segments = await get_transcriber().transcribe(video_path)
                meeting.transcript = "\n".join(f"[{s.speaker}] {s.text}" for s in segments)
                transcript_segments = [
                    {"speaker": s.speaker, "text": s.text, "start": s.start, "end": s.end}
                    for s in segments
                ]

            require_transcript(segments)
            # Commit raw text AND diarization before any provider call, including
            # failures. Preserve the original text independently of review edits.
            extracted_json = dict(meeting.extracted_json or {})
            extracted_json.setdefault("raw_transcript", meeting.transcript)
            extracted_json["transcript_segments"] = transcript_segments
            meeting.extracted_json = extracted_json
            meeting.state = ProcessingState.extracting
            await commit()
            result = validate_extraction(
                await get_extractor().extract(segments),
                transcript_only=settings.extractor_impl == "transcript_only",
            )
            await commit()  # Stop here if cancellation arrived during extraction.
            meeting.summary = result.summary
            # Match the imported recording to the organiser's Outlook event. Doing
            # this before the final commit ensures the review page receives the real
            # meeting date, attendee list and speaker-name candidates.
            try:
                from app.services.recording_enrichment import enrich_recording_from_outlook

                if settings.graph_impl != "mock":
                    matching_upns = list(await db.scalars(
                        select(RegisteredUser.upn).where(RegisteredUser.is_subscribed.is_(True))
                    ))
                    await enrich_recording_from_outlook(
                        meeting, drive_id, drive_item_id, candidate_upns=matching_upns
                    )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "Could not match recording %s to an Outlook meeting", drive_item_id
                )

            # Preserve Outlook matching metadata collected before extraction.
            extracted_json = dict(meeting.extracted_json or {})
            extracted_json.update(result.model_dump())
            if meeting.recorded_at:
                extracted_json["meeting_time"] = meeting.recorded_at.isoformat()
            # Keep diarization timestamps for reviewer-only representative audio
            # samples. The human-readable transcript deliberately remains plain text.
            extracted_json["transcript_segments"] = transcript_segments
            meeting.extracted_json = extracted_json
            # A job may be retried after a late notification failure. Replace
            # extracted actions rather than duplicating the previous attempt.
            await db.execute(delete(ActionItem).where(ActionItem.meeting_id == meeting.id))
            for ai in result.action_items:
                db.add(ActionItem(
                    meeting_id=meeting.id,
                    task=ai.action or ai.task,
                    owner=ai.assigned_to or ai.owner,
                    deadline_text=ai.due_date or ai.deadline_text,
                    deadline_iso=ai.deadline_iso,
                    confidence=ai.confidence,
                    source_quote=ai.source_quote,
                    raw=ai.model_dump(),
                    approved=False,
                ))

            all_participant_upns = set(extra)
            if meeting.organizer_upn:
                all_participant_upns.add(meeting.organizer_upn)
            if owner_upn:
                all_participant_upns.add(owner_upn)

            # Only create participant rows for registered users — unregistered attendees
            # can request historical access later via POST /reviews/{id}/request-access.
            registered_upns = set(await db.scalars(
                select(RegisteredUser.upn).where(
                    RegisteredUser.upn.in_(all_participant_upns)
                )
            ))
            existing_upns = set(await db.scalars(
                select(MeetingParticipant.user_upn).where(
                    MeetingParticipant.meeting_id == meeting.id
                )
            ))
            participant_upns = registered_upns  # only registered users get visibility
            for upn in participant_upns:
                if upn not in existing_upns:
                    db.add(MeetingParticipant(
                        meeting_id=meeting.id,
                        user_upn=upn,
                        is_organizer=(upn == meeting.organizer_upn),
                    ))

            meeting.state = ProcessingState.awaiting_review
            await commit(complete=True)
            await _send_ready_for_review(meeting, len(participant_upns))

    except JobCancelled:
        await db.rollback()
        raise
    except Exception as e:
        meeting.state = ProcessingState.failed
        meeting.error = public_job_error(e)
        await commit()
        raise
