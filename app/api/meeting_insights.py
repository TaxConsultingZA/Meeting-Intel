"""Saved-transcript analysis independent of recording processing."""
import asyncio
import hashlib
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..models import MeetingInsightDraft, ActionItem
from ..services import meeting_insights as service
from ..services.action_review import confirmed_deadline_iso
from .reviews import _authorize, _require_editor, _is_admin
from .deps import require_registered
router = APIRouter(prefix="/reviews")
class Candidate(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    source_quote: str = Field(min_length=1, max_length=10000)
    owner: str | None = Field(default=None, max_length=255)
    deadline: str | None = Field(default=None, max_length=255)
    status: Literal["pending_confirmation", "confirmed", "rejected"] = "pending_confirmation"
    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Candidate cannot be blank")
        return value.strip()

class DraftEdit(BaseModel):
    version: int = Field(ge=1)
    summary: str = Field(max_length=30000)
    actions: list[Candidate] = Field(max_length=30)
    decisions: list[Candidate] = Field(max_length=30)
def output(d):
    return None if d is None else {"version": d.version, "status": d.status, "provider": "mock", **d.payload}
def fingerprint(t):
    return hashlib.sha256(t.encode()).hexdigest()
@router.get("/{meeting_id}/insights")
async def read(meeting_id: UUID, db: AsyncSession = Depends(get_db), upn: str = Depends(require_registered)):
    await _authorize(db, meeting_id, upn, allow_admin=await _is_admin(db, upn))
    return output(await db.get(MeetingInsightDraft, meeting_id))
@router.post("/{meeting_id}/insights")
async def generate(meeting_id: UUID, db: AsyncSession = Depends(get_db), upn: str = Depends(require_registered)):
    admin = await _is_admin(db, upn)
    meeting = await _authorize(db, meeting_id, upn, for_update=True, allow_admin=admin)
    _require_editor(meeting, upn, is_admin=admin)
    if not meeting.transcript or not meeting.transcript.strip():
        raise HTTPException(409, "A saved transcript is required")
    draft = await db.get(MeetingInsightDraft, meeting_id)
    if draft and draft.status != "failed":
        return output(draft)
    if draft is None:
        draft = MeetingInsightDraft(meeting_id=meeting_id, version=1, payload={}, status="running",
                                    transcript_hash=fingerprint(meeting.transcript))
        db.add(draft)
    try:
        payload = await asyncio.wait_for(service.adapter.analyze(meeting.transcript), timeout=10)
        validated = DraftEdit(version=1, **payload)
        for item in validated.actions + validated.decisions:
            if item.source_quote not in meeting.transcript:
                raise ValueError("Ungrounded output")
            item.status = "pending_confirmation"
        draft.payload = validated.model_dump(exclude={"version"})
        draft.status = "awaiting_review"
        draft.transcript_hash = fingerprint(meeting.transcript)
    except Exception:
        draft.status = "failed"
        draft.payload = {"summary": "", "actions": [], "decisions": []}
    await db.commit()
    return output(draft)
@router.put("/{meeting_id}/insights")
async def save(meeting_id: UUID, body: DraftEdit, db: AsyncSession = Depends(get_db), upn: str = Depends(require_registered)):
    admin = await _is_admin(db, upn)
    meeting = await _authorize(db, meeting_id, upn, for_update=True, allow_admin=admin)
    _require_editor(meeting, upn, is_admin=admin)
    draft = await db.get(MeetingInsightDraft, meeting_id)
    if not draft or draft.version != body.version or draft.status != "awaiting_review":
        raise HTTPException(409, "Draft changed; reload before saving")
    if fingerprint(meeting.transcript or "") != draft.transcript_hash:
        raise HTTPException(409, "Saved transcript changed; draft requires reconciliation")
    for kind in ("actions", "decisions"):
        items, old = getattr(body, kind), draft.payload[kind]
        if len(items) != len(old) or any(i.source_quote != o["source_quote"] for i, o in zip(items, old)):
            raise HTTPException(422, "Source evidence is immutable")
        for item, source in zip(items, old):
            if source["status"] == "confirmed" and item.model_dump() != source:
                raise HTTPException(409, "Confirmed candidates cannot be edited here")
            if kind == "actions" and item.status == "confirmed" and source["status"] != "confirmed":
                db.add(ActionItem(meeting_id=meeting_id, task=item.text, owner=item.owner,
                    deadline_text=item.deadline, deadline_iso=confirmed_deadline_iso(item.deadline), source_quote=item.source_quote, approved=True,
                    edited_by=upn, raw={"origin": "mock_insight_human_confirmed"}))
    draft.payload = body.model_dump(exclude={"version"})
    draft.version += 1
    draft.reviewed_by = upn
    await db.commit()
    return output(draft)
