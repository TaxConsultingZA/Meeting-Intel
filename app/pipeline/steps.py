import os
import tempfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Meeting, ActionItem, MeetingParticipant, ProcessingState, RegisteredUser
from ..graph import client as graph
from .transcribe import get_transcriber
from .extract import get_extractor

settings = get_settings()

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
    db: AsyncSession, drive_item_id: str, drive_id: str, owner_upn: str | None = None
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
    meeting = await db.scalar(select(Meeting).where(Meeting.drive_item_id == drive_item_id))
    if meeting is None:
        meta = await graph.get_drive_item(drive_id, drive_item_id)
        user_node = (meta.get("createdBy", {}).get("user", {}) or {})
        organizer = (
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
        await db.commit()
        await db.refresh(meeting)

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
            await db.commit()

    # Notify participants before any AI processing (POPIA Section 18).
    extra = await graph.get_event_attendees(drive_id, drive_item_id)

    # Persist the full attendee list so historical-access requests can be verified later,
    # even after the pipeline filters participants down to registered users only.
    all_attendee_upns = list({*extra, *(p for p in [meeting.organizer_upn, owner_upn] if p)})
    if meeting.attendees_raw is None:
        meeting.attendees_raw = all_attendee_upns
        await db.commit()

    await _send_popia_notice(meeting, extra)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            meeting.state = ProcessingState.downloading
            await db.commit()

            # AssemblyAI accepts MP4 directly — no ffmpeg audio extraction needed
            video_path = os.path.join(tmp, "rec.mp4")
            await graph.download_drive_item(drive_id, drive_item_id, video_path)

            meeting.state = ProcessingState.transcribing
            await db.commit()
            all_upns = list({*extra, *(p for p in [meeting.organizer_upn, owner_upn] if p)})
            await _send_processing_started(meeting, all_upns)
            segments = await get_transcriber().transcribe(video_path)
            meeting.transcript = "\n".join(f"[{s.speaker}] {s.text}" for s in segments)

            meeting.state = ProcessingState.extracting
            await db.commit()
            result = await get_extractor().extract(segments)
            meeting.summary = result.summary
            meeting.extracted_json = result.model_dump()
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
            await db.commit()
            await _send_ready_for_review(meeting, len(participant_upns))

    except Exception as e:
        meeting.state = ProcessingState.failed
        meeting.error = str(e)[:2000]
        await db.commit()
        raise
