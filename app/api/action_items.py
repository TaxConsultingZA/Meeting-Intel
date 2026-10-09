"""Read-only approved actions, scoped to existing meeting visibility."""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import ActionItem, Meeting, MeetingParticipant, ProcessingState
from ..schemas import ApprovedActionItemOut, ApprovedActionItemsPageOut
from ..services.access import NO_VIEW_ACCESS_TYPES
from .deps import require_registered


router = APIRouter()


@router.get("/action-items", response_model=ApprovedActionItemsPageOut)
async def list_action_items(
    response: Response,
    view: Literal["mine", "all"] = "mine",
    meeting: str = Query(default="", max_length=255),
    owner: str = Query(default="", max_length=255),
    deadline: str = Query(default="", max_length=255),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    upn: str = Depends(require_registered),
):
    response.headers["Cache-Control"] = "no-store"
    access = select(MeetingParticipant.id).where(
        MeetingParticipant.meeting_id == Meeting.id,
        func.lower(MeetingParticipant.user_upn) == upn,
        MeetingParticipant.access_type.notin_(NO_VIEW_ACCESS_TYPES),
    ).exists()
    query = select(
        ActionItem.id, ActionItem.task, ActionItem.owner,
        ActionItem.deadline_iso, ActionItem.deadline_text, ActionItem.source_quote,
        Meeting.id.label("meeting_id"), Meeting.title.label("meeting_title"),
    ).join(Meeting, Meeting.id == ActionItem.meeting_id).where(
        ActionItem.approved.is_(True),
        Meeting.state.in_([ProcessingState.approved, ProcessingState.sent]),
        access,
    )
    if view == "mine":
        # Owner is extracted free text, not an assignment identity. Never infer names.
        query = query.where(func.lower(func.trim(ActionItem.owner)) == upn)
    if meeting.strip():
        query = query.where(func.lower(Meeting.title).contains(meeting.strip().lower(), autoescape=True))
    if owner.strip():
        query = query.where(func.lower(ActionItem.owner).contains(owner.strip().lower(), autoescape=True))
    if deadline.strip():
        value = deadline.strip().lower()
        query = query.where(or_(
            func.lower(ActionItem.deadline_iso).contains(value, autoescape=True),
            func.lower(ActionItem.deadline_text).contains(value, autoescape=True),
        ))
    query = query.order_by(Meeting.recorded_at.desc().nullslast(), ActionItem.id).offset(offset).limit(limit + 1)
    rows = (await db.execute(query)).mappings().all()
    return ApprovedActionItemsPageOut(
        items=[ApprovedActionItemOut(**row) for row in rows[:limit]],
        has_more=len(rows) > limit,
        viewer_upn=upn,
    )
