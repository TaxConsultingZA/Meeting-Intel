"""Completion authority and persistence, without network or workflow side effects."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.action_items import router
from app.api.deps import registered_user
from app.db import get_db
from app.models import ActionItem, Meeting, MeetingParticipant, ProcessingState, RegisteredUser


@pytest.fixture
def api():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for table in [RegisteredUser.__table__, Meeting.__table__, MeetingParticipant.__table__, ActionItem.__table__]:
        table.create(engine)
    session = Session(engine, expire_on_commit=False)
    user = RegisteredUser(id=uuid4(), upn="alice@taxconsulting.co.za", is_admin=False)
    meeting = Meeting(drive_item_id="synthetic-completion", state=ProcessingState.approved,
                      organizer_upn=user.upn, summary="Approved notes", transcript="Saved evidence",
                      approved_by=user.upn, approved_at=datetime.now(timezone.utc))
    session.add_all([user, meeting]); session.flush()
    participant = MeetingParticipant(meeting_id=meeting.id, user_upn=user.upn, access_type="participant")
    item = ActionItem(meeting_id=meeting.id, task="Locked wording", approved=True, owner="Another extracted name")
    session.add_all([participant, item]); session.commit()
    db = MagicMock()
    db.get = AsyncMock(side_effect=session.get)
    db.scalar = AsyncMock(side_effect=session.scalar)
    db.execute = AsyncMock(side_effect=session.execute)
    db.commit = AsyncMock(side_effect=session.commit)
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[registered_user] = lambda: user
    with TestClient(app) as client:
        yield client, session, user, meeting, participant, item, db
    session.close(); engine.dispose()


def put(client, item, completed=True):
    return client.put(f"/action-items/{item.id}/completion", json={"completed": completed})


def test_complete_idempotent_reopen_and_approval_unchanged(api):
    client, session, user, meeting, participant, item, db = api
    approval = (meeting.approved_by, meeting.approved_at.replace(tzinfo=timezone.utc), meeting.summary, meeting.transcript, item.task, item.approved)
    first = put(client, item); assert first.status_code == 200
    completed = first.json()
    assert completed["completed_at"] and completed["completed_by_id"] == str(user.id)
    assert completed["can_complete"] is True
    assert put(client, item).json() == completed
    session.expire_all()
    assert session.get(ActionItem, item.id).completed_at is not None
    assert put(client, item, False).json() == {"completed_at": None, "completed_by_id": None, "can_complete": True}
    assert put(client, item, False).status_code == 200
    assert approval == (meeting.approved_by, meeting.approved_at.replace(tzinfo=timezone.utc), meeting.summary, meeting.transcript, item.task, item.approved)
    db.add.assert_not_called()


@pytest.mark.parametrize("role,allowed", [("organiser", True), ("admin", True), ("editor", True),
    ("viewer", False), ("owner_only", False), ("shared_editor", False), ("revoked", False), ("outsider", False)])
def test_authority_requires_existing_view_and_editor_access(api, role, allowed):
    client, session, user, meeting, participant, item, db = api
    meeting.organizer_upn = "other@taxconsulting.co.za"
    if role == "organiser": participant.is_organizer = True
    if role == "admin": user.is_admin = True; participant.access_type = "revoked"
    if role == "editor": participant.edit_access_status = "approved"
    if role == "owner_only": item.owner = user.upn
    if role == "shared_editor": participant.access_type = "shared"; participant.edit_access_status = "approved"
    if role == "revoked": participant.access_type = "revoked"; participant.edit_access_status = "approved"
    if role == "outsider": participant.user_upn = "outsider@taxconsulting.co.za"
    session.commit()
    response = put(client, item)
    assert response.status_code == (200 if allowed else 403)
    if not allowed: assert item.completed_at is None; db.commit.assert_not_awaited()
    rows = client.get("/action-items?view=all").json()["items"]
    if role in {"outsider", "revoked", "admin"}: assert rows == []
    else: assert rows[0]["can_complete"] is allowed


@pytest.mark.parametrize("state,approved", [(ProcessingState.awaiting_review, True), (ProcessingState.failed, True), (ProcessingState.approved, False)])
def test_only_approved_tasks_can_change_completion(api, state, approved):
    client, session, user, meeting, participant, item, db = api
    meeting.state = state; item.approved = approved; session.commit()
    assert put(client, item).status_code == 409
    assert item.completed_at is None
    db.commit.assert_not_awaited()


def test_sent_notes_and_revocation_rechecked_on_reopen(api):
    client, session, user, meeting, participant, item, db = api
    meeting.state = ProcessingState.sent; session.commit()
    assert put(client, item).status_code == 200
    participant.access_type = "revoked"; session.commit()
    assert put(client, item, False).status_code == 403
    assert item.completed_at is not None


def test_invalid_payload_and_missing_item(api):
    client, session, user, meeting, participant, item, db = api
    for body in [{}, {"completed": "false"}, {"completed": None}]:
        assert client.put(f"/action-items/{item.id}/completion", json=body).status_code == 422
    assert client.put(f"/action-items/{uuid4()}/completion", json={"completed": True}).status_code == 404


def test_authentication_and_registration_required_for_completion(api):
    client, session, user, meeting, participant, item, db = api
    client.app.dependency_overrides.pop(registered_user)
    assert put(client, item).status_code == 401
    response = client.put(f"/action-items/{item.id}/completion", json={"completed": True},
                          headers={"Authorization": "Bearer mock:missing@taxconsulting.co.za"})
    assert response.status_code == 403
    assert item.completed_at is None
