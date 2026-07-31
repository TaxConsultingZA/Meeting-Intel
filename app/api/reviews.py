from datetime import datetime, timezone
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import Meeting, ActionItem, MeetingParticipant, ProcessingState, RegisteredUser
from ..schemas import (
    MeetingOut, ActionItemOut, ActionItemEdit, ShareMeetingIn, ApproveMeetingIn
)
from ..graph import client as graph
from ..email_templates import build_meeting_email
from .deps import current_user, require_registered  # noqa: F401 — re-exported; tests may import from here

settings = get_settings()
router = APIRouter()


async def _authorize(db: AsyncSession, meeting_id, upn: str) -> Meeting:
    """Row-level authorisation: load a meeting and verify the caller is a participant.

    Raises 404 if the meeting doesn't exist, 403 if the caller has no participant
    row for it.  Returns the fully-loaded Meeting ORM object on success.
    """
    m = await db.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )
    if not m:
        raise HTTPException(404)
    if not any(p.user_upn == upn for p in m.participants):
        raise HTTPException(403, "Not a participant of this meeting")
    return m


def _to_out(m: Meeting) -> MeetingOut:
    """Convert a Meeting ORM instance to its Pydantic API output schema."""
    known_recipients = {
        value.strip().lower()
        for value in (m.attendees_raw or [])
        if isinstance(value, str) and "@" in value
    }
    known_recipients.update(p.user_upn.lower() for p in m.participants)
    if m.organizer_upn:
        known_recipients.add(m.organizer_upn.lower())
    return MeetingOut(
        id=str(m.id), title=m.title, state=m.state, summary=m.summary,
        organizer_upn=m.organizer_upn, extracted_json=m.extracted_json, error=m.error,
        email_recipients=sorted(known_recipients),
        approved_recipients=m.approved_recipients or [],
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


@router.get("/reviews/all", response_model=list[MeetingOut])
async def all_meetings(db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    rows = (await db.scalars(
        select(Meeting)
        .join(MeetingParticipant)
        .where(MeetingParticipant.user_upn == upn)
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )).unique().all()
    return [_to_out(m) for m in rows]


@router.get("/reviews/pending", response_model=list[MeetingOut])
async def pending(db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    rows = (await db.scalars(
        select(Meeting)
        .join(MeetingParticipant)
        .where(
            Meeting.state == ProcessingState.awaiting_review,
            MeetingParticipant.user_upn == upn,
            or_(
                MeetingParticipant.is_organizer.is_(True),
                Meeting.organizer_upn == upn,
            ),
        )
    )).unique().all()
    return [_to_out(m) for m in rows]


@router.get("/reviews/historical", response_model=list[MeetingOut])
async def historical_meetings(db: AsyncSession = Depends(get_db), upn: str = Depends(require_registered)):
    """List meetings the caller attended before they registered, with no current access.

    These are meetings where the caller's UPN appears in ``attendees_raw`` but they
    have no ``MeetingParticipant`` row.  The caller can request access to each one.
    """
    from sqlalchemy import not_, exists, cast
    from sqlalchemy.dialects.postgresql import JSONB

    participant_exists = exists().where(
        MeetingParticipant.meeting_id == Meeting.id,
        MeetingParticipant.user_upn == upn,
    )
    rows = (await db.scalars(
        select(Meeting)
        .where(
            Meeting.attendees_raw.isnot(None),
            Meeting.attendees_raw.contains(cast([upn], JSONB)),
            not_(participant_exists),
        )
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )).unique().all()
    return [_to_out(m) for m in rows]


@router.get("/reviews/{meeting_id}", response_model=MeetingOut)
async def get_meeting(meeting_id: str, db: AsyncSession = Depends(get_db),
                      upn: str = Depends(current_user)):
    m = await _authorize(db, meeting_id, upn)
    return _to_out(m)


@router.patch("/reviews/action-items/{item_id}")
async def edit_item(item_id: str, edit: ActionItemEdit,
                    db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    item = await db.get(ActionItem, item_id)
    if not item:
        raise HTTPException(404)
    meeting = await _authorize(db, item.meeting_id, upn)
    _require_organizer(meeting, upn)
    for field, val in edit.model_dump(exclude_unset=True).items():
        setattr(item, field, val)
    item.edited_by = upn
    await db.commit()
    return {"ok": True}


@router.post("/reviews/{meeting_id}/approve")
async def approve(meeting_id: str, db: AsyncSession = Depends(get_db),
                  upn: str = Depends(current_user),
                  body: ApproveMeetingIn = Body(default=ApproveMeetingIn())):
    m = await _authorize(db, meeting_id, upn)
    _require_organizer(m, upn)

    known_recipients = {
        value.strip().lower()
        for value in (m.attendees_raw or [])
        if isinstance(value, str) and "@" in value
    }
    known_recipients.update(p.user_upn.lower() for p in m.participants)
    if m.organizer_upn:
        known_recipients.add(m.organizer_upn.lower())
    unknown = set(body.recipients) - known_recipients
    if unknown:
        raise HTTPException(
            422,
            f"Recipients were not part of this meeting: {', '.join(sorted(unknown))}",
        )

    for a in m.action_items:
        a.approved = True
    m.state = ProcessingState.approved
    m.approved_recipients = body.recipients
    m.approved_by = upn
    m.approved_at = datetime.now(timezone.utc)
    await db.commit()

    # The explicit organiser approval is the send gate. AUTO_SEND_EMAIL is no
    # longer used here: selected recipients are never contacted before this POST.
    if settings.emails_enabled and body.recipients and m.organizer_upn:
        subject, email_body = build_meeting_email(m)
        await graph.send_mail(
            settings.mail_sender_upn or m.organizer_upn,
            m.approved_recipients,
            subject,
            email_body,
        )
        m.state = ProcessingState.sent
        await db.commit()

    return {"ok": True, "state": m.state}


@router.post("/reviews/{meeting_id}/share")
async def share_meeting(meeting_id: str, body: ShareMeetingIn,
                        db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    """Share a meeting transcript with another @taxconsulting.co.za colleague.

    Only the meeting organiser can share.  Creates a ``MeetingParticipant`` row
    with ``access_type='shared'`` so the recipient sees the meeting in their dashboard.
    """
    m = await _authorize(db, meeting_id, upn)
    if m.organizer_upn != upn:
        raise HTTPException(403, "Only the meeting organiser can share this transcript")

    already = await db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == m.id,
            MeetingParticipant.user_upn == body.recipient_upn,
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
    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import JSONB

    m = await db.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(selectinload(Meeting.participants), selectinload(Meeting.action_items))
    )
    if not m:
        raise HTTPException(404, "Meeting not found")

    attendees = m.attendees_raw or []
    if upn not in attendees:
        raise HTTPException(403, "You were not listed as an attendee of this meeting")

    already = await db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == m.id,
            MeetingParticipant.user_upn == upn,
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
