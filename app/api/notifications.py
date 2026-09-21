from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Meeting, MeetingParticipant, ProcessingState
from ..services.access import NO_VIEW_ACCESS_TYPES
from .reviews import current_user

router = APIRouter()

# Maps a pipeline state to the notification type string and human-readable message
# shown in the bell dropdown.  States not in this map are silently excluded.
_TYPE_MAP = {
    ProcessingState.awaiting_review: ("ready_for_review", "Meeting notes ready for your review"),
    ProcessingState.sent:            ("notes_sent",        "Meeting notes approved and sent to participants"),
    ProcessingState.failed:          ("failed",            "Recording could not be processed"),
    ProcessingState.transcribing:    ("processing",        "Meeting recording is being transcribed"),
    ProcessingState.extracting:      ("processing",        "Extracting action items and insights"),
}


@router.get("/notifications")
async def get_notifications(
    db: AsyncSession = Depends(get_db),
    upn: str = Depends(current_user),
):
    """Return the 30 most recent activity notifications for the authenticated user.

    Only meetings where the user is a participant and whose state appears in
    ``_TYPE_MAP`` are included.  Meetings with a deep-link (awaiting_review,
    sent) include a ``link`` field the frontend uses to navigate directly.
    """
    rows = await db.scalars(
        select(Meeting)
        .join(MeetingParticipant)
        .where(
            func.lower(MeetingParticipant.user_upn) == upn,
            MeetingParticipant.access_type.notin_(NO_VIEW_ACCESS_TYPES),
        )
        .order_by(Meeting.created_at.desc())
        .limit(30)
    )
    meetings = rows.unique().all()

    notifications = []
    for m in meetings:
        if m.state not in _TYPE_MAP:
            continue
        ntype, message = _TYPE_MAP[m.state]
        notifications.append({
            "id": str(m.id),
            "type": ntype,
            "title": m.title or "Untitled Meeting",
            "message": message,
            "time": m.created_at.isoformat(),
            "link": f"/meetings/{m.id}" if m.state in (
                ProcessingState.awaiting_review, ProcessingState.sent
            ) else None,
        })
    return notifications
