"""Search real SQL against an isolated in-memory database, without network access."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import current_user
from app.api.reviews import router
from app.db import get_db
from app.models import (
    ActionItem,
    Meeting,
    MeetingDecision,
    MeetingParticipant,
    ProcessingState,
)


@pytest.fixture
def search_api():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for table in [Meeting.__table__, MeetingParticipant.__table__, ActionItem.__table__, MeetingDecision.__table__]:
        table.create(engine)
    session = Session(engine)

    def add(title, summary=None, task=None, access="participant", user="alice", day=1, transcript=None):
        meeting = Meeting(title=title, drive_item_id=title, summary=summary, transcript=transcript,
                          state=ProcessingState.awaiting_review,
                          recorded_at=datetime(2026, 10, day, tzinfo=UTC))
        session.add(meeting)
        session.flush()
        session.add(MeetingParticipant(meeting_id=meeting.id, user_upn=user, access_type=access))
        if task:
            session.add(ActionItem(meeting_id=meeting.id, task=task))
        session.commit()
        return meeting

    db = MagicMock()
    db.execute = AsyncMock(side_effect=session.execute)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: "alice"
    with TestClient(app) as client:
        yield client, add, session, db, app
    session.close()
    engine.dispose()


def test_summary_action_case_and_time_order(search_api):
    client, add, *_ = search_api
    first = add("Summary match", summary="BUDGET planning", day=2)
    second = add("Action match", task="Review budget", day=3, access="shared")
    add("budget title only", transcript="budget secret")
    response = client.get("/reviews/search", params={"q": "BuDgEt"})
    assert response.status_code == 200
    rows = response.json()
    assert [r["id"] for r in rows] == [str(second.id), str(first.id)]
    assert rows[0]["matched_action_items"] is True
    assert rows[1]["matched_summary"] is True
    assert set(rows[0]) == {"id", "title", "recorded_at", "matched_summary", "matched_action_items", "matched_decisions"}


def test_permissions_isolation_and_revocation(search_api):
    client, add, session, _, app = search_api
    visible = add("Visible", summary="needle")
    for access in ["request_view", "request_edit", "revoked"]:
        add("Secret " + access, summary="needle", task="needle", access=access)
    add("Other user", summary="needle", user="bob")
    assert [r["title"] for r in client.get("/reviews/search?q=needle").json()] == ["Visible"]
    participant = session.query(MeetingParticipant).filter_by(meeting_id=visible.id).one()
    participant.access_type = "revoked"
    session.commit()
    assert client.get("/reviews/search?q=needle").json() == []
    app.dependency_overrides[current_user] = lambda: "bob"
    assert [r["title"] for r in client.get("/reviews/search?q=needle").json()] == ["Other user"]


def test_empty_no_results_literal_wildcards_and_limit(search_api):
    client, add, _, db, _ = search_api
    for index in range(53):
        add(f"Meeting {index}", summary="needle")
    assert len(client.get("/reviews/search?q=needle").json()) == 50
    for q in ["absent", "%", "_"]:
        assert client.get("/reviews/search", params={"q": q}).json() == []
    db.execute.reset_mock()
    assert client.get("/reviews/search?q=%20%20").json() == []
    db.execute.assert_not_called()
    assert client.get("/reviews/search", params={"q": "x" * 256}).status_code == 422


def test_requires_login(search_api):
    client, _, _, _, app = search_api
    app.dependency_overrides.pop(current_user)
    assert client.get("/reviews/search?q=needle").status_code == 401
