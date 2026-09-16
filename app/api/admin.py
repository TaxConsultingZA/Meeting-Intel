"""Admin API — user registration and operational access visibility.

All endpoints require the caller to be a registered admin (``is_admin=True``).
The first admin is bootstrapped via the ``ADMIN_UPNS`` env var at application startup.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import get_db
from ..email_templates import build_welcome_email
from ..graph import client as graph
from ..models import BusinessUnit, Meeting, MeetingParticipant, ProcessedItem, ProcessingState, RecordingJob, RecordingProcessingRequest, RegisteredUser
from ..schemas import AdminRevokeAccessIn, BusinessUnitOut, RegisteredUserOut, RegisterUserIn, SyncStateOut, UpdateUserIn
from ..services.sync_state import list_sync_status
from ..utils.identity import normalize_upn
from .deps import current_user

settings = get_settings()

router = APIRouter(prefix="/admin", tags=["admin"])
NO_VIEW_ACCESS_TYPES = {"request_view", "request_edit", "revoked"}
NO_ADMIN_PROCESSING_APPROVAL_STATES = {
    ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent,
}


async def _require_admin(upn: str = Depends(current_user), db: AsyncSession = Depends(get_db)) -> str:
    """FastAPI dependency: reject non-admin callers with 403."""
    user = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    if not user or not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return upn


def _user_to_out(u: RegisteredUser) -> RegisteredUserOut:
    """Convert a RegisteredUser ORM row to its API response shape."""
    return RegisteredUserOut(
        upn=u.upn,
        display_name=u.display_name,
        business_unit_id=u.business_unit_id,
        business_unit_name=u.business_unit.name if u.business_unit else None,
        is_admin=u.is_admin,
        is_subscribed=u.is_subscribed,
        subscribed_at=u.subscribed_at.isoformat() if u.subscribed_at else None,
        registered_at=u.registered_at.isoformat(),
    )


@router.get("/business-units", response_model=list[BusinessUnitOut])
async def list_business_units(db: AsyncSession = Depends(get_db),
                               _upn: str = Depends(current_user)):
    """Return all available business units.  Any authenticated domain user can call this."""
    rows = (await db.scalars(select(BusinessUnit).order_by(BusinessUnit.name))).all()
    return [BusinessUnitOut(id=b.id, name=b.name) for b in rows]


@router.get("/users", response_model=list[RegisteredUserOut])
async def list_users(db: AsyncSession = Depends(get_db), _upn: str = Depends(_require_admin)):
    """Return all registered platform users with their business unit assignment."""
    from sqlalchemy.orm import selectinload
    rows = (await db.scalars(
        select(RegisteredUser)
        .options(selectinload(RegisteredUser.business_unit))
        .order_by(RegisteredUser.registered_at)
    )).all()
    return [_user_to_out(u) for u in rows]


@router.get("/users/{upn}/sync-status", response_model=list[SyncStateOut])
async def get_user_sync_status(
    upn: str, db: AsyncSession = Depends(get_db), _admin_upn: str = Depends(_require_admin),
):
    """Return another registered user's safe Calendar/OneDrive diagnostics."""
    target_upn = normalize_upn(upn)
    exists = await db.scalar(select(RegisteredUser.id).where(RegisteredUser.upn == target_upn))
    if exists is None:
        raise HTTPException(404, "User not found")
    return await list_sync_status(db, target_upn)


@router.get("/meetings")
async def list_operational_meetings(
    db: AsyncSession = Depends(get_db), _upn: str = Depends(_require_admin),
):
    """Return cross-user operational metadata without transcript or note content."""
    meetings = (await db.scalars(
        select(Meeting).options(selectinload(Meeting.participants))
        .order_by(Meeting.created_at.desc()).limit(200)
    )).all()
    if not meetings:
        return []
    item_ids = [meeting.drive_item_id for meeting in meetings]
    meeting_ids = [meeting.id for meeting in meetings]
    jobs = (await db.scalars(
        select(RecordingJob).where(RecordingJob.drive_item_id.in_(item_ids))
        .order_by(RecordingJob.created_at.desc())
    )).all()
    requests = (await db.scalars(
        select(RecordingProcessingRequest).where(
            (RecordingProcessingRequest.meeting_id.in_(meeting_ids))
            | (RecordingProcessingRequest.drive_item_id.in_(item_ids))
        ).order_by(RecordingProcessingRequest.created_at.desc())
    )).all()
    tracked_items = set(await db.scalars(
        select(ProcessedItem.drive_item_id).where(
            ProcessedItem.drive_item_id.in_(item_ids), ProcessedItem.drive_id.is_not(None)
        )
    ))
    latest_job = {}
    for job in jobs:
        latest_job.setdefault(job.drive_item_id, job)
    latest_request = {}
    for request in requests:
        latest_request.setdefault(request.meeting_id or request.drive_item_id, request)
    return [{
        "id": str(meeting.id),
        "title": meeting.title,
        "recorded_at": meeting.recorded_at,
        "organizer_upn": meeting.organizer_upn,
        "owner_upn": latest_job[meeting.drive_item_id].owner_upn if meeting.drive_item_id in latest_job else meeting.organizer_upn,
        "meeting_status": meeting.state.value,
        "recording_status": "tracked" if meeting.drive_item_id in tracked_items else "unknown",
        "job_status": latest_job[meeting.drive_item_id].status if meeting.drive_item_id in latest_job else None,
        "request_status": (
            latest_request.get(meeting.id) or latest_request.get(meeting.drive_item_id)
        ).status if (meeting.id in latest_request or meeting.drive_item_id in latest_request) else None,
        "access": [{
            "user_upn": participant.user_upn,
            "is_organizer": participant.is_organizer or normalize_upn(participant.user_upn) == normalize_upn(meeting.organizer_upn),
            "view_access": True,
            "edit_access": participant.edit_access_status == "approved" or participant.is_organizer or normalize_upn(participant.user_upn) == normalize_upn(meeting.organizer_upn),
        } for participant in meeting.participants if participant.access_type not in NO_VIEW_ACCESS_TYPES],
    } for meeting in meetings]


@router.get("/access-requests")
async def list_access_requests(db: AsyncSession = Depends(get_db), _upn: str = Depends(_require_admin)):
    """Return processing, view, and edit requests across every meeting."""
    processing = (await db.scalars(select(RecordingProcessingRequest).order_by(RecordingProcessingRequest.created_at.desc()))).all()
    participants = (await db.scalars(
        select(MeetingParticipant)
        .where(or_(
            MeetingParticipant.access_type.in_({"request_view", "request_edit"}),
            (MeetingParticipant.edit_requested_at.is_not(None)) & (MeetingParticipant.access_type != "revoked"),
        ))
        .options(selectinload(MeetingParticipant.meeting))
        .order_by(MeetingParticipant.edit_requested_at.desc())
    )).all()
    user_ids = {request.requester_user_id for request in processing} | {request.recording_owner_user_id for request in processing}
    users = (await db.scalars(select(RegisteredUser).where(RegisteredUser.id.in_(user_ids)))).all() if user_ids else []
    users_by_id = {user.id: user for user in users}
    processing_item_ids = {request.drive_item_id for request in processing}
    processing_meetings = (await db.scalars(
        select(Meeting).where(Meeting.drive_item_id.in_(processing_item_ids))
    )).all() if processing_item_ids else []
    meetings_by_item = {meeting.drive_item_id: meeting for meeting in processing_meetings}
    completed_item_ids = set(await db.scalars(
        select(RecordingJob.drive_item_id).where(
            RecordingJob.drive_item_id.in_(processing_item_ids), RecordingJob.status == "completed",
        )
    )) if processing_item_ids else set()
    rows = []
    for request in processing:
        event = request.event_snapshot or {}
        requester = users_by_id.get(request.requester_user_id)
        owner = users_by_id.get(request.recording_owner_user_id)
        existing_meeting = meetings_by_item.get(request.drive_item_id)
        has_previous_result = bool(existing_meeting and (
            existing_meeting.transcript or existing_meeting.state in NO_ADMIN_PROCESSING_APPROVAL_STATES
        )) or request.drive_item_id in completed_item_ids
        rows.append({
            "id": str(request.id), "meeting_id": str(request.meeting_id) if request.meeting_id else None,
            "meeting": event.get("subject") or "Untitled meeting",
            "requester_upn": requester.upn if requester else None, "requester_name": requester.display_name if requester else None,
            "owner_upn": owner.upn if owner else None,
            "organizer_upn": (event.get("organizer") or {}).get("emailAddress", {}).get("address"),
            "request_type": "processing", "status": request.status, "requested_at": request.created_at,
            "can_approve": request.status == "pending" and not has_previous_result,
        })
    for participant in participants:
        meeting = participant.meeting
        is_view_request = participant.access_type == "request_view" or (
            participant.access_type == "historical"
            and participant.edit_access_status == "none"
            and participant.edit_decided_at is not None
        )
        status = "approved" if is_view_request and participant.edit_decided_at is not None and participant.edit_access_status == "none" else participant.edit_access_status
        rows.append({
            "id": str(participant.id), "meeting_id": str(participant.meeting_id),
            "meeting": meeting.title or "Untitled meeting", "requester_upn": participant.user_upn,
            "requester_name": None, "owner_upn": meeting.organizer_upn, "organizer_upn": meeting.organizer_upn,
            "request_type": "view" if is_view_request else "edit",
            "status": status, "requested_at": participant.edit_requested_at,
        })
    return sorted(rows, key=lambda row: row["requested_at"].timestamp() if row["requested_at"] else float("-inf"), reverse=True)


@router.post("/meetings/{meeting_id}/access/{user_upn}/revoke")
async def revoke_meeting_access(meeting_id: str, user_upn: str, body: AdminRevokeAccessIn,
                                db: AsyncSession = Depends(get_db), admin_upn: str = Depends(_require_admin)):
    """Revoke one non-organizer permission while retaining its participant audit row."""
    meeting = await db.scalar(
        select(Meeting).where(Meeting.id == meeting_id)
        .options(selectinload(Meeting.participants)).with_for_update()
    )
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    participant = next((row for row in meeting.participants if normalize_upn(row.user_upn) == normalize_upn(user_upn)), None)
    if not participant:
        raise HTTPException(404, "Meeting access not found")
    if participant.is_organizer or normalize_upn(participant.user_upn) == normalize_upn(meeting.organizer_upn):
        raise HTTPException(409, "Organizer access cannot be revoked")
    now = datetime.now(timezone.utc)
    if body.access_type == "view":
        if participant.access_type in NO_VIEW_ACCESS_TYPES:
            raise HTTPException(409, "View access is not currently granted")
        participant.access_type = "revoked"
        participant.edit_access_status = "denied"
    else:
        if participant.edit_access_status != "approved":
            raise HTTPException(409, "Edit access is not currently granted")
        participant.edit_access_status = "denied"
    participant.edit_decided_at = now
    participant.edit_decided_by = admin_upn
    await db.commit()
    return {"ok": True, "access_type": body.access_type, "status": "revoked"}


@router.post("/users", response_model=RegisteredUserOut, status_code=201)
async def register_user(body: RegisterUserIn, db: AsyncSession = Depends(get_db),
                        _upn: str = Depends(_require_admin)):
    """Register a new @taxconsulting.co.za user and assign them to a business unit."""
    from sqlalchemy.orm import selectinload

    existing = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == body.upn))
    if existing:
        raise HTTPException(409, f"{body.upn} is already registered")

    if body.business_unit_id is not None:
        bu = await db.get(BusinessUnit, body.business_unit_id)
        if not bu:
            raise HTTPException(404, "Business unit not found")

    user = RegisteredUser(
        upn=body.upn,
        display_name=body.display_name,
        business_unit_id=body.business_unit_id,
        is_admin=body.is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # reload with relationship so business_unit_name is available
    user = await db.scalar(
        select(RegisteredUser)
        .where(RegisteredUser.upn == body.upn)
        .options(selectinload(RegisteredUser.business_unit))
    )

    if settings.emails_enabled:
        try:
            bu_name = user.business_unit.name if user.business_unit else None
            subject, html = build_welcome_email(
                upn=user.upn,
                display_name=user.display_name,
                business_unit=bu_name,
                app_url=settings.app_url,
            )
            await graph.send_mail(
                sender=settings.mail_sender_upn or "stanley@taxconsulting.co.za",
                to_upns=[user.upn],
                subject=subject,
                html_body=html,
            )
        except Exception:
            pass  # never let a failed welcome email roll back the registration

    return _user_to_out(user)


@router.patch("/users/{upn}", response_model=RegisteredUserOut)
async def update_user(upn: str, body: UpdateUserIn, db: AsyncSession = Depends(get_db),
                      _admin_upn: str = Depends(_require_admin)):
    """Update an existing registered user's display name, business unit, or admin flag."""
    from sqlalchemy.orm import selectinload

    user = await db.scalar(
        select(RegisteredUser)
        .where(RegisteredUser.upn == upn)
        .options(selectinload(RegisteredUser.business_unit))
    )
    if not user:
        raise HTTPException(404, f"{upn} is not registered")

    if body.business_unit_id is not None:
        bu = await db.get(BusinessUnit, body.business_unit_id)
        if not bu:
            raise HTTPException(404, "Business unit not found")

    if body.display_name is not None:
        user.display_name = body.display_name
    if body.business_unit_id is not None:
        user.business_unit_id = body.business_unit_id
    if body.is_admin is not None:
        user.is_admin = body.is_admin

    await db.commit()
    user = await db.scalar(
        select(RegisteredUser)
        .where(RegisteredUser.upn == upn)
        .options(selectinload(RegisteredUser.business_unit))
    )
    return _user_to_out(user)


@router.delete("/users/{upn}", status_code=204)
async def remove_user(upn: str, db: AsyncSession = Depends(get_db),
                      admin_upn: str = Depends(_require_admin)):
    """Remove a user from the platform.  An admin cannot remove themselves."""
    if upn == admin_upn:
        raise HTTPException(400, "Cannot remove your own admin account")

    user = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    if not user:
        raise HTTPException(404, f"{upn} is not registered")

    await db.delete(user)
    await db.commit()
