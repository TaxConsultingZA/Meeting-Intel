"""Actual confirmation/list/completion API flow; all rows are synthetic.
"""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import action_items, meeting_insights, reviews
from app.api.deps import registered_user, require_registered
from app.db import get_db
from app.models import ActionItem, Meeting, MeetingInsightDraft, MeetingParticipant, ProcessingState, RegisteredUser


def test_actual_confirmation_then_pending_notes_task_lifecycle(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (RegisteredUser, Meeting, MeetingParticipant, ActionItem, MeetingInsightDraft):
        model.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    user = RegisteredUser(id=uuid4(), upn="alice@taxconsulting.co.za", is_admin=False)
    meeting = Meeting(id=uuid4(), drive_item_id="synthetic-independent-action", title="Synthetic pending notes",
        organizer_upn=user.upn, state=ProcessingState.awaiting_review, summary="Unapproved notes",
        transcript="Please prepare a report.\nPlease archive evidence.\nPlease check totals.")
    session.add_all([user, meeting]); session.flush()
    participant = MeetingParticipant(meeting_id=meeting.id, user_upn=user.upn, access_type="participant")
    payload = {"summary": "Synthetic draft", "actions": [
        {"text": text, "source_quote": quote, "owner": user.upn, "deadline": "2026-11-03", "status": "pending_confirmation"}
        for text, quote in [("Prepare report", "Please prepare a report."),
                            ("Archive evidence", "Please archive evidence."), ("Check totals", "Please check totals.")]], "decisions": []}
    draft = MeetingInsightDraft(meeting_id=meeting.id, version=1, status="awaiting_review", payload=payload,
        transcript_hash=hashlib.sha256(meeting.transcript.encode()).hexdigest())
    session.add_all([participant, draft]); session.commit()
    db = MagicMock()
    for method in ("get", "scalar", "scalars", "execute", "commit", "delete"):
        setattr(db, method, AsyncMock(side_effect=getattr(session, method)))
    db.add = session.add
    app = FastAPI(); app.include_router(meeting_insights.router); app.include_router(action_items.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[registered_user] = lambda: user
    app.dependency_overrides[require_registered] = lambda: user.upn
    send = AsyncMock(side_effect=AssertionError("Confirmation and reminders must never send mail"))
    monkeypatch.setattr(reviews.graph, "send_mail", send)
    # Even with mail enabled in this process, no confirmation/completion path sends.
    monkeypatch.setattr(reviews.settings, "emails_enabled", True)
    before = (meeting.state, meeting.approved_by, meeting.approved_at, meeting.summary, meeting.transcript,
              meeting.email_delivery_status, meeting.approved_recipients)
    with TestClient(app) as client:
        states = {"pending": client.get("/action-items?view=all").json()}
        assert states["pending"]["items"] == []
        edit = {"version": 1, **json.loads(json.dumps(payload))}
        edit["actions"][0]["status"] = "confirmed"
        edit["actions"][1]["status"] = "rejected"
        response = client.put(f"/reviews/{meeting.id}/insights", json=edit)
        assert response.status_code == 200, response.text
        assert client.put(f"/reviews/{meeting.id}/insights", json=edit).status_code == 409
        assert len(session.scalars(select(ActionItem)).all()) == 1
        states["confirmed"] = client.get("/action-items?view=all").json()
        item = states["confirmed"]["items"][0]
        assert item["task"] == "Prepare report" and item["can_complete"] is True
        assert item["deadline_iso"] == "2026-11-03"
        url = f'/action-items/{item["id"]}/completion'
        response = client.put(url, json={"completed": True}); assert response.status_code == 200
        states["complete_response"] = response.json()
        states["completed"] = client.get("/action-items").json()
        assert states["completed"]["items"][0]["completed_at"]
        response = client.put(url, json={"completed": False}); assert response.status_code == 200
        states["reopen_response"] = response.json()
        states["reopened"] = client.get("/action-items").json()
        assert states["reopened"]["items"][0]["completed_at"] is None
        participant.access_type = "revoked"; session.commit()
        states["revoked"] = client.get("/action-items?view=all").json()
        assert states["revoked"]["items"] == []
        assert client.put(url, json={"completed": True}).status_code == 403
        assert before == (meeting.state, meeting.approved_by, meeting.approved_at, meeting.summary, meeting.transcript,
                          meeting.email_delivery_status, meeting.approved_recipients)
        send.assert_not_awaited()
        destination = os.environ.get("ACTION_FLOW_FIXTURE")
        if destination:
            Path(destination).write_text(json.dumps(states, indent=2) + "\n", encoding="utf-8")
    session.close(); engine.dispose()
