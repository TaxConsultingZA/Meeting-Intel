from datetime import datetime, timezone
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import (
    Meeting, ActionItem, MeetingEmailAudit, MeetingParticipant, ProcessingState, ProcessedItem,
    RegisteredUser,
)
from ..schemas import (
    MeetingOut, ActionItemOut, ActionItemEdit, ShareMeetingIn, ApproveMeetingIn,
    EmailPreviewOut, TranscriptEdit, SpeakerMappingIn, EditAccessDecisionIn,
    EditAccessRequestOut, SendMeetingCopyIn,
)
from ..graph import client as graph
from ..email_templates import build_meeting_email
from ..utils.identity import normalize_upn, normalize_upns
from ..services.job_control import public_job_error
from .deps import current_user, require_registered  # noqa: F401 — re-exported; tests may import from here

settings = get_settings()
router = APIRouter()


def is_local_test_meeting(meeting) -> bool:
    # Keep the no-delivery safeguard for any legacy fixture rows. The retired
    # seed tool and local-file audio path are intentionally no longer supported.
    return (
        str(getattr(meeting, "drive_item_id", "")).startswith("meeting-intel-test-")
        and bool((getattr(meeting, "extracted_json", None) or {}).get("local_test_data"))
    )


async def _authorize(
    db: AsyncSession, meeting_id, upn: str, *, for_update: bool = False
) -> Meeting:
    """Row-level authorisation: load a meeting and verify the caller is a participant.

    Raises 404 if the meeting doesn't exist, 403 if the caller has no participant
    row for it.  Returns the fully-loaded Meeting ORM object on success.
    """
    query = (
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )
    if for_update:
        query = query.with_for_update()
    m = await db.scalar(query)
    if not m:
        raise HTTPException(404)
    if not any(normalize_upn(p.user_upn) == upn for p in m.participants):
        raise HTTPException(403, "Not a participant of this meeting")
    return m


def _participant_for(m: Meeting, upn: str | None) -> MeetingParticipant | None:
    if not upn:
        return None
    return next((p for p in m.participants if normalize_upn(p.user_upn) == upn), None)


def _is_attendee_participant(m: Meeting, participant: MeetingParticipant | None) -> bool:
    """Distinguish real attendees from users who only received shared view access."""
    if not participant:
        return False
    participant_upn = normalize_upn(participant.user_upn)
    return (
        getattr(participant, "access_type", None) in {"participant", "historical"}
        or participant_upn in normalize_upns(m.attendees_raw)
    )


def _to_out(m: Meeting, upn: str | None = None) -> MeetingOut:
    """Convert a Meeting ORM instance to its Pydantic API output schema."""
    known_recipients = set(normalize_upns(m.attendees_raw))
    known_recipients.update(p.user_upn.lower() for p in m.participants)
    if m.organizer_upn:
        known_recipients.add(m.organizer_upn.lower())
    caller = _participant_for(m, upn)
    is_organizer = bool(upn) and (
        normalize_upn(m.organizer_upn) == upn or bool(caller and caller.is_organizer)
    )
    extracted = m.extracted_json or {}
    raw_candidates = extracted.get("speaker_candidates") or []
    speaker_candidates = set(known_recipients)
    for candidate in raw_candidates:
        if isinstance(candidate, str):
            value = normalize_upn(candidate) or candidate.strip()
        elif isinstance(candidate, dict):
            value = normalize_upn(candidate.get("email")) or str(candidate.get("name") or "").strip()
        else:
            value = ""
        if value:
            speaker_candidates.add(value)
    sample_labels = []
    if is_organizer:
        sample_labels = list(dict.fromkeys(
            str(segment.get("speaker") or "").strip()
            for segment in (extracted.get("transcript_segments") or [])
            if isinstance(segment, dict) and str(segment.get("speaker") or "").strip()
        ))
    edit_requests = [
        EditAccessRequestOut(
            requester_upn=p.user_upn,
            status=p.edit_access_status,
            requested_at=p.edit_requested_at,
        )
        for p in m.participants
        if p.edit_access_status == "pending"
    ] if is_organizer else []
    return MeetingOut(
        id=str(m.id), title=m.title, state=m.state, summary=m.summary,
        transcript=m.transcript,
        organizer_upn=m.organizer_upn, extracted_json=m.extracted_json, error=public_job_error(m.error),
        recorded_at=m.recorded_at,
        email_recipients=sorted(known_recipients),
        approved_recipients=m.approved_recipients or [],
        is_organizer=is_organizer,
        can_edit=is_organizer or bool(
            _is_attendee_participant(m, caller) and caller.edit_access_status == "approved"
        ),
        can_request_edit_access=bool(
            not is_organizer
            and _is_attendee_participant(m, caller)
            and caller.edit_access_status in {"none", "pending", "denied"}
        ),
        edit_access_status="organizer" if is_organizer else (caller.edit_access_status if caller else "none"),
        edit_access_requests=edit_requests,
        speaker_candidates=sorted(speaker_candidates),
        speaker_mappings=extracted.get("speaker_mappings", {}),
        speaker_sample_labels=sample_labels,
        action_items=[
            ActionItemOut(
                id=str(a.id), task=a.task, owner=a.owner,
                deadline_text=a.deadline_text, deadline_iso=a.deadline_iso,
                confidence=a.confidence, source_quote=a.source_quote, approved=a.approved,
            ) for a in m.action_items
        ],
    )


def _require_organizer(m: Meeting, upn: str) -> None:
    """The human-in-the-loop reviewer is the meeting organiser only."""
    organizer = (m.organizer_upn or "").lower()
    participant_marks_organizer = any(
        p.user_upn.lower() == upn and p.is_organizer for p in m.participants
    )
    if organizer != upn and not participant_marks_organizer:
        raise HTTPException(403, "Only the meeting organiser can review and approve")


def _require_editor(m: Meeting, upn: str) -> None:
    try:
        _require_organizer(m, upn)
        return
    except HTTPException:
        participant = _participant_for(m, upn)
        if (
            not _is_attendee_participant(m, participant)
            or participant.edit_access_status != "approved"
        ):
            raise HTTPException(403, "Edit access must be approved by the meeting organiser")


def _require_approved_attendee(m: Meeting, upn: str) -> MeetingParticipant:
    """Allow approved non-organizer editors without granting review authority."""
    participant = _participant_for(m, upn)
    if (
        not _is_attendee_participant(m, participant)
        or participant.is_organizer
        or normalize_upn(m.organizer_upn) == upn
        or participant.edit_access_status != "approved"
    ):
        raise HTTPException(403, "Approved attendee access is required")
    return participant


def _require_awaiting_review(m: Meeting) -> None:
    if m.state != ProcessingState.awaiting_review:
        raise HTTPException(409, "Meeting notes can only be changed while awaiting review")


def _speaker_sample_window(m: Meeting, speaker_label: str) -> tuple[float, float] | None:
    """Pick the longest diarized utterance for a short, representative sample."""
    matches: list[tuple[float, float]] = []
    for segment in (m.extracted_json or {}).get("transcript_segments") or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("speaker") or "").strip().casefold() != speaker_label.strip().casefold():
            continue
        try:
            start = max(0.0, float(segment["start"]))
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            matches.append((start, end))
    if not matches:
        return None
    start, end = max(matches, key=lambda pair: pair[1] - pair[0])
    sample_start = max(0.0, start - 0.25)
    return sample_start, min(end + 0.25, sample_start + 12.0)


async def _build_speaker_sample(
    drive_id: str, drive_item_id: str, start: float, end: float
) -> bytes:
    """Download the source recording and render a compact mono MP3 excerpt."""
    from imageio_ffmpeg import get_ffmpeg_exe

    with tempfile.TemporaryDirectory(prefix="meeting-intel-sample-") as tmp:
        source_path = os.path.join(tmp, "recording.mp4")
        sample_path = os.path.join(tmp, "sample.mp3")
        await graph.download_drive_item(drive_id, drive_item_id, source_path)
        command = [
            get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-i", source_path,
            "-t", f"{end - start:.3f}", "-vn", "-ac", "1", "-ar", "22050",
            "-codec:a", "libmp3lame", "-b:a", "64k", sample_path,
        ]
        try:
            await asyncio.to_thread(
                subprocess.run, command, check=True, capture_output=True, timeout=180
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(502, "Could not create the speaker audio sample") from exc
        with open(sample_path, "rb") as sample_file:
            return sample_file.read()


@router.get("/reviews/all", response_model=list[MeetingOut])
async def all_meetings(db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    rows = (await db.scalars(
        select(Meeting)
        .join(MeetingParticipant)
        .where(func.lower(MeetingParticipant.user_upn) == upn)
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )).unique().all()
    return [_to_out(m, upn) for m in rows]


@router.get("/reviews/pending", response_model=list[MeetingOut])
async def pending(db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    rows = (await db.scalars(
        select(Meeting)
        .join(MeetingParticipant)
        .where(
            Meeting.state == ProcessingState.awaiting_review,
            func.lower(MeetingParticipant.user_upn) == upn,
            or_(
                MeetingParticipant.is_organizer.is_(True),
                func.lower(Meeting.organizer_upn) == upn,
            ),
        )
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )).unique().all()
    return [_to_out(m, upn) for m in rows]


@router.get("/reviews/historical", response_model=list[MeetingOut])
async def historical_meetings(db: AsyncSession = Depends(get_db), upn: str = Depends(require_registered)):
    """List meetings the caller attended before they registered, with no current access.

    These are meetings where the caller's UPN appears in ``attendees_raw`` but they
    have no ``MeetingParticipant`` row.  The caller can request access to each one.
    """
    from sqlalchemy import not_, exists

    participant_exists = exists().where(
        MeetingParticipant.meeting_id == Meeting.id,
        func.lower(MeetingParticipant.user_upn) == upn,
    )
    rows = (await db.scalars(
        select(Meeting)
        .where(
            Meeting.attendees_raw.isnot(None),
            not_(participant_exists),
        )
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )).unique().all()
    return [_to_out(m, upn) for m in rows if upn in normalize_upns(m.attendees_raw)]


@router.get("/reviews/{meeting_id}", response_model=MeetingOut)
async def get_meeting(meeting_id: str, db: AsyncSession = Depends(get_db),
                      upn: str = Depends(current_user)):
    m = await _authorize(db, meeting_id, upn)
    return _to_out(m, upn)


@router.get("/reviews/{meeting_id}/email-preview", response_model=EmailPreviewOut)
async def email_preview(meeting_id: str, db: AsyncSession = Depends(get_db),
                        upn: str = Depends(current_user)):
    """Render the exact branded HTML that approval would send, without sending it."""
    m = await _authorize(db, meeting_id, upn)
    subject, html = build_meeting_email(m)
    return EmailPreviewOut(subject=subject, html=html)


@router.patch("/reviews/action-items/{item_id}")
async def edit_item(item_id: str, edit: ActionItemEdit,
                    db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    item = await db.get(ActionItem, item_id)
    if not item:
        raise HTTPException(404)
    meeting = await _authorize(db, item.meeting_id, upn)
    _require_editor(meeting, upn)
    _require_awaiting_review(meeting)
    for field, val in edit.model_dump(exclude_unset=True).items():
        setattr(item, field, val)
    item.edited_by = upn
    await db.commit()
    return {"ok": True}


@router.patch("/reviews/{meeting_id}/transcript")
async def edit_transcript(meeting_id: str, body: TranscriptEdit,
                          db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    meeting = await _authorize(db, meeting_id, upn)
    _require_editor(meeting, upn)
    _require_awaiting_review(meeting)
    meeting.transcript = body.transcript
    await db.commit()
    return {"ok": True}


@router.put("/reviews/{meeting_id}/speaker-mappings")
async def save_speaker_mappings(meeting_id: str, body: SpeakerMappingIn,
                                db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    meeting = await _authorize(db, meeting_id, upn)
    _require_editor(meeting, upn)
    _require_awaiting_review(meeting)
    allowed = normalize_upns(meeting.attendees_raw)
    allowed.update(normalize_upn(p.user_upn) for p in meeting.participants)
    mappings: dict[str, str | None] = {}
    for label, candidate in body.mappings.items():
        clean_label = label.strip()
        clean_candidate = normalize_upn(candidate) if candidate else None
        if not clean_label.lower().startswith("speaker "):
            raise HTTPException(422, f"Invalid speaker label: {clean_label}")
        if clean_candidate and clean_candidate not in allowed:
            raise HTTPException(422, f"Speaker mapping is not a meeting participant: {clean_candidate}")
        mappings[clean_label] = clean_candidate
    extracted = dict(meeting.extracted_json or {})
    extracted["speaker_mappings"] = mappings
    meeting.extracted_json = extracted
    await db.commit()
    return {"ok": True, "speaker_mappings": mappings}


@router.get("/reviews/{meeting_id}/speaker-samples/{speaker_label}")
async def speaker_sample(meeting_id: str, speaker_label: str,
                         db: AsyncSession = Depends(get_db),
                         upn: str = Depends(current_user)):
    """Return a short voice sample. Only the meeting reviewer may listen."""
    meeting = await _authorize(db, meeting_id, upn)
    _require_organizer(meeting, upn)
    window = _speaker_sample_window(meeting, speaker_label)
    if not window:
        raise HTTPException(404, "No timed transcript segment exists for this speaker")

    source = await db.scalar(
        select(ProcessedItem).where(ProcessedItem.drive_item_id == meeting.drive_item_id)
    )
    if not source or not source.drive_id:
        raise HTTPException(404, "The source recording is no longer available")

    audio = await _build_speaker_sample(
        source.drive_id, meeting.drive_item_id, window[0], window[1]
    )
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline",
        },
    )


@router.post("/reviews/{meeting_id}/edit-access")
async def request_edit_access(meeting_id: str, db: AsyncSession = Depends(get_db),
                              upn: str = Depends(current_user)):
    meeting = await _authorize(db, meeting_id, upn)
    _require_awaiting_review(meeting)
    try:
        _require_organizer(meeting, upn)
        return {"ok": True, "status": "organizer"}
    except HTTPException:
        pass
    participant = _participant_for(meeting, upn)
    if not _is_attendee_participant(meeting, participant):
        raise HTTPException(403, "Only attendees of this meeting may request edit access")
    if participant.edit_access_status == "pending":
        return {"ok": True, "status": "pending"}
    if participant.edit_access_status == "approved":
        raise HTTPException(409, "Edit access has already been approved")
    participant.edit_access_status = "pending"
    participant.edit_requested_at = datetime.now(timezone.utc)
    participant.edit_decided_at = None
    participant.edit_decided_by = None
    await db.commit()
    return {"ok": True, "status": "pending"}


@router.patch("/reviews/{meeting_id}/edit-access/{requester_upn}")
async def decide_edit_access(meeting_id: str, requester_upn: str, body: EditAccessDecisionIn,
                             db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    meeting = await _authorize(db, meeting_id, upn, for_update=True)
    _require_organizer(meeting, upn)
    _require_awaiting_review(meeting)
    participant = _participant_for(meeting, normalize_upn(requester_upn))
    if (
        not _is_attendee_participant(meeting, participant)
        or participant.is_organizer
        or normalize_upn(participant.user_upn) == normalize_upn(meeting.organizer_upn)
    ):
        raise HTTPException(404, "Edit request not found")
    if participant.edit_access_status != "pending":
        raise HTTPException(409, "Only pending edit requests can be decided")
    participant.edit_access_status = "approved" if body.approved else "denied"
    participant.edit_decided_at = datetime.now(timezone.utc)
    participant.edit_decided_by = upn
    await db.commit()
    return {"ok": True, "status": participant.edit_access_status}


@router.post("/reviews/{meeting_id}/approve")
async def approve(meeting_id: str, db: AsyncSession = Depends(get_db),
                  upn: str = Depends(current_user),
                  body: ApproveMeetingIn = Body(default=ApproveMeetingIn())):
    # Serialize concurrent approvals. Without this lock, two browser requests
    # can both observe awaiting_review and send the same email twice.
    m = await _authorize(db, meeting_id, upn, for_update=True)
    _require_organizer(m, upn)

    known_recipients = set(normalize_upns(m.attendees_raw))
    known_recipients.update(p.user_upn.lower() for p in m.participants)
    if m.organizer_upn:
        known_recipients.add(m.organizer_upn.lower())
    unknown = set(body.recipients) - known_recipients
    if unknown:
        raise HTTPException(
            422,
            f"Recipients were not part of this meeting: {', '.join(sorted(unknown))}",
        )

    recipients = sorted(set(body.recipients))
    subject, email_body = build_meeting_email(m)
    fingerprint = hashlib.sha256(json.dumps(
        {"meeting_id": str(m.id), "recipients": recipients, "subject": subject, "html": email_body},
        sort_keys=True,
    ).encode("utf-8")).hexdigest()

    # Repeated delivery of the exact same approval is idempotent.
    if m.email_delivery_status == "sent" and m.email_delivery_fingerprint == fingerprint:
        return {"ok": True, "state": m.state, "already_sent": True}
    if m.email_delivery_status == "sending":
        raise HTTPException(
            409,
            "Email delivery is already in progress or its outcome is unknown; automatic resend is blocked",
        )
    _require_awaiting_review(m)

    # The explicit organiser approval is the send gate. AUTO_SEND_EMAIL is no
    # longer used here: selected recipients are never contacted before this POST.
    # Send before committing approval so a Graph failure leaves the meeting in
    # awaiting_review and the organiser can safely retry from the UI.
    sent = False
    if settings.emails_enabled and not is_local_test_meeting(m) and recipients and m.organizer_upn:
        m.email_delivery_status = "sending"
        m.email_delivery_fingerprint = fingerprint
        m.email_delivery_error = None
        m.email_delivery_attempts += 1
        m.approved_recipients = recipients
        # Persist the delivery claim before calling Graph. If the web process
        # dies after Graph accepts the mail, a later request will be blocked
        # instead of silently sending a duplicate.
        await db.commit()
        try:
            await graph.send_mail(
                settings.mail_sender_upn or m.organizer_upn,
                recipients,
                subject,
                email_body,
            )
        except Exception as exc:
            m.email_delivery_status = "failed"
            m.email_delivery_error = str(exc)[:1000]
            await db.commit()
            raise HTTPException(
                502,
                "Email delivery failed; the meeting remains awaiting review and can be retried",
            ) from exc
        m.email_delivery_status = "sent"
        m.email_delivery_error = None
        sent = True
    else:
        m.email_delivery_status = "not_required"
        m.email_delivery_fingerprint = fingerprint
        m.email_delivery_error = None

    for a in m.action_items:
        a.approved = True
    m.state = ProcessingState.sent if sent else ProcessingState.approved
    m.approved_recipients = recipients
    m.approved_by = upn
    m.approved_at = datetime.now(timezone.utc)
    await db.commit()

    return {"ok": True, "state": m.state}


@router.post("/reviews/{meeting_id}/send-copy")
async def send_copy_to_self(meeting_id: str, body: SendMeetingCopyIn,
                            db: AsyncSession = Depends(get_db),
                            upn: str = Depends(current_user)):
    """Send approved notes to an approved attendee's own verified company UPN."""
    meeting = await _authorize(db, meeting_id, upn)
    _require_approved_attendee(meeting, upn)
    if body.recipient_upn != upn:
        raise HTTPException(403, "Approved attendees may only send a copy to themselves")
    if meeting.state not in {ProcessingState.approved, ProcessingState.sent}:
        raise HTTPException(409, "A personal copy is available only after organiser approval")

    sender = settings.mail_sender_upn or meeting.organizer_upn
    if not sender:
        raise HTTPException(409, "No sender is configured for this meeting")

    delivery_enabled = settings.emails_enabled and not is_local_test_meeting(meeting)
    audit = MeetingEmailAudit(
        meeting_id=meeting.id,
        actor_upn=upn,
        recipient_upn=upn,
        action="self_copy",
        status="sending" if delivery_enabled else "disabled",
    )
    db.add(audit)
    await db.commit()
    if not delivery_enabled:
        return {"ok": True, "sent": False}

    subject, email_body = build_meeting_email(meeting)
    try:
        await graph.send_mail(sender, [upn], subject, email_body)
    except Exception as exc:
        audit.status = "failed"
        audit.error = str(exc)[:1000]
        await db.commit()
        raise HTTPException(502, "Personal copy delivery failed") from exc

    audit.status = "sent"
    audit.error = None
    await db.commit()
    return {"ok": True, "sent": True}


@router.post("/reviews/{meeting_id}/share")
async def share_meeting(meeting_id: str, body: ShareMeetingIn,
                        db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    """Share a meeting transcript with another @taxconsulting.co.za colleague.

    Only the meeting organiser can share.  Creates a ``MeetingParticipant`` row
    with ``access_type='shared'`` so the recipient sees the meeting in their dashboard.
    """
    m = await _authorize(db, meeting_id, upn)
    if normalize_upn(m.organizer_upn) != upn:
        raise HTTPException(403, "Only the meeting organiser can share this transcript")

    already = await db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == m.id,
            func.lower(MeetingParticipant.user_upn) == body.recipient_upn,
        )
    )
    if already:
        return {"ok": True, "message": "Already has access"}

    db.add(MeetingParticipant(
        meeting_id=m.id,
        user_upn=body.recipient_upn,
        is_organizer=False,
        access_type="shared",
    ))
    await db.commit()
    return {"ok": True, "message": f"Shared with {body.recipient_upn}"}


@router.post("/reviews/{meeting_id}/request-access")
async def request_historical_access(meeting_id: str, db: AsyncSession = Depends(get_db),
                                    upn: str = Depends(require_registered)):
    """Auto-grant access to a historical meeting if the caller was an attendee.

    Checks ``attendees_raw`` — if the caller's UPN is present, creates a
    ``MeetingParticipant`` row with ``access_type='historical'`` immediately.
    No approval step required: being listed as an attendee is proof of presence.
    """
    m = await db.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )
    if not m:
        raise HTTPException(404, "Meeting not found")

    attendees = normalize_upns(m.attendees_raw)
    if upn not in attendees:
        raise HTTPException(403, "You were not listed as an attendee of this meeting")

    already = await db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == m.id,
            func.lower(MeetingParticipant.user_upn) == upn,
        )
    )
    if already:
        return {"ok": True, "message": "Already have access"}

    db.add(MeetingParticipant(
        meeting_id=m.id,
        user_upn=upn,
        is_organizer=False,
        access_type="historical",
    ))
    await db.commit()
    return {"ok": True, "message": "Access granted"}
