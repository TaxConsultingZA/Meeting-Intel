"""Approved actions and independent completion, scoped to existing meeting access."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from ..db import get_db
from ..models import ActionItem, Meeting, MeetingParticipant, ProcessingState, RegisteredUser
from ..schemas import ApprovedActionItemOut, ApprovedActionItemsPageOut, TaskCompletionIn, TaskCompletionOut
from ..services.access import NO_VIEW_ACCESS_TYPES
from .deps import registered_user
from .reviews import _authorize, _require_editor, can_complete_task


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
    user: RegisteredUser = Depends(registered_user),
):
    upn = user.upn
    response.headers["Cache-Control"] = "no-store"
    access = select(MeetingParticipant.id).where(
        MeetingParticipant.meeting_id == Meeting.id,
        func.lower(MeetingParticipant.user_upn) == upn,
        MeetingParticipant.access_type.notin_(NO_VIEW_ACCESS_TYPES),
    ).exists()
    query = select(ActionItem, Meeting).options(
        load_only(ActionItem.id, ActionItem.meeting_id, ActionItem.task, ActionItem.owner,
                  ActionItem.deadline_iso, ActionItem.deadline_text, ActionItem.source_quote,
                  ActionItem.confidence, ActionItem.approved, ActionItem.completed_at, ActionItem.completed_by_id),
        load_only(Meeting.id, Meeting.title, Meeting.state, Meeting.organizer_upn, Meeting.attendees_raw),
        selectinload(Meeting.participants),
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
    rows = (await db.execute(query)).all()
    return ApprovedActionItemsPageOut(
        items=[ApprovedActionItemOut(
            id=item.id, task=item.task, owner=item.owner, meeting_id=meeting.id, meeting_title=meeting.title,
            deadline_iso=item.deadline_iso, deadline_text=item.deadline_text,
            source_quote=item.source_quote, confidence=item.confidence,
            completed_at=item.completed_at, completed_by_id=item.completed_by_id,
            can_complete=can_complete_task(meeting, item, upn, is_admin=bool(user.is_admin)),
        ) for item, meeting in rows[:limit]],
        has_more=len(rows) > limit,
        viewer_upn=upn,
    )


@router.put("/action-items/{item_id}/completion", response_model=TaskCompletionOut)
async def set_task_completion(
    item_id: UUID, body: TaskCompletionIn, response: Response,
    db: AsyncSession = Depends(get_db), user: RegisteredUser = Depends(registered_user),
):
    response.headers["Cache-Control"] = "no-store"
    item = await db.get(ActionItem, item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    # Match the existing parent-meeting lock order. Do not invoke the note-edit
    # awaiting-review guard: task execution happens after note approval.
    meeting = await _authorize(db, item.meeting_id, user.upn, for_update=True, allow_admin=bool(user.is_admin))
    _require_editor(meeting, user.upn, is_admin=bool(user.is_admin))
    item = await db.scalar(select(ActionItem).where(ActionItem.id == item_id)
                           .with_for_update().execution_options(populate_existing=True))
    if not item or not item.approved or meeting.state not in (ProcessingState.approved, ProcessingState.sent):
        raise HTTPException(409, "Only approved tasks in approved meeting notes can be completed or reopened")
    if body.completed:
        if item.completed_at is None:
            item.completed_at = datetime.now(timezone.utc)
            item.completed_by_id = user.id
    else:
        item.completed_at = None
        item.completed_by_id = None
    result = TaskCompletionOut(completed_at=item.completed_at, completed_by_id=item.completed_by_id, can_complete=True)
    await db.commit()
    return result
