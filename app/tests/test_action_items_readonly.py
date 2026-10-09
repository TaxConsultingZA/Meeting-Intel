"""Execute read-only action queries against an isolated SQLite database."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.action_items import router
from app.db import get_db
from app.models import ActionItem, Meeting, MeetingParticipant, ProcessingState


@pytest.fixture
def api():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for table in [Meeting.__table__, MeetingParticipant.__table__, ActionItem.__table__]:
        table.create(engine)
    session = Session(engine)
    actor = "alice@taxconsulting.co.za"

    def add(title, state=ProcessingState.approved, access="participant", owner=actor, approved=True, participant=actor):
        meeting = Meeting(title=title, state=state, drive_item_id=title,
                          recorded_at=datetime(2026, 10, 8, tzinfo=timezone.utc))
        session.add(meeting)
        session.flush()
        session.add(MeetingParticipant(meeting_id=meeting.id, user_upn=participant, access_type=access))
        session.add(ActionItem(meeting_id=meeting.id, task=f"Task {title}", owner=owner,
                              approved=approved, deadline_iso="2026-10-12", deadline_text="Monday",
                              source_quote="Please send the report."))
    add("Budget", owner="  ALICE@taxconsulting.co.za  ")
    add("Tax 100%", state=ProcessingState.sent, owner="Alice")
    add("Shared", access="shared", owner="Bob")
    add("Draft", state=ProcessingState.awaiting_review)
    add("Unapproved", approved=False)
    add("Failed", state=ProcessingState.failed)
    add("Pending view", access="request_view")
    add("Pending edit", access="request_edit")
    add("Revoked", access="revoked")
    add("Private", participant="bob@taxconsulting.co.za")
    session.commit()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=SimpleNamespace(upn=actor, is_admin=False))
    db.execute = AsyncMock(side_effect=session.execute)
    db.commit = AsyncMock()
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, db, {"Authorization": f"Bearer mock:{actor}"}
    session.close()
    engine.dispose()


def titles(response):
    assert response.status_code == 200
    return {item["meeting_title"] for item in response.json()["items"]}


def test_all_only_approved_and_accessible_without_admin_bypass(api):
    client, db, headers = api
    db.scalar.return_value.is_admin = True
    response = client.get("/action-items?view=all", headers=headers)
    assert titles(response) == {"Budget", "Tax 100%", "Shared"}
    assert response.headers["cache-control"] == "no-store"
    item = response.json()["items"][0]
    assert set(item) == {"id", "task", "meeting_id", "meeting_title", "owner", "deadline_iso", "deadline_text", "source_quote"}
    db.commit.assert_not_awaited()
    db.add.assert_not_called()


def test_mine_requires_exact_email_not_extracted_name(api):
    client, _, headers = api
    assert titles(client.get("/action-items", headers=headers)) == {"Budget"}


@pytest.mark.parametrize("params,expected", [
    ({"meeting": "BUDG"}, {"Budget"}),
    ({"owner": "alice"}, {"Budget", "Tax 100%"}),
    ({"deadline": "MONDAY"}, {"Budget", "Tax 100%", "Shared"}),
    ({"deadline": "2026-10"}, {"Budget", "Tax 100%", "Shared"}),
    ({"meeting": "%"}, {"Tax 100%"}),
    ({"owner": "_"}, set()),
    ({"meeting": "Budget", "owner": "Bob"}, set()),
])
def test_filters_are_case_insensitive_literal_and_composable(api, params, expected):
    client, _, headers = api
    assert titles(client.get("/action-items", params={"view": "all", **params}, headers=headers)) == expected


def test_pagination_is_bounded_and_has_no_duplicates(api):
    client, _, headers = api
    ids = []
    for offset in range(3):
        response = client.get("/action-items", params={"view": "all", "limit": 1, "offset": offset}, headers=headers)
        assert response.status_code == 200
        page = response.json()
        assert page["has_more"] == (offset < 2)
        ids.extend(item["id"] for item in page["items"])
    assert len(set(ids)) == 3


@pytest.mark.parametrize("params", [{"view": "invalid"}, {"limit": 101}, {"limit": 0}, {"offset": -1}, {"owner": "x" * 256}])
def test_invalid_filters_rejected(api, params):
    client, db, headers = api
    assert client.get("/action-items", params=params, headers=headers).status_code == 422
    db.execute.assert_not_awaited()


def test_authentication_registration_and_no_write_routes(api):
    client, db, headers = api
    assert client.get("/action-items").status_code == 401
    db.scalar.return_value = None
    assert client.get("/action-items", headers=headers).status_code == 403
    db.execute.assert_not_awaited()
    for method in ["post", "patch", "put", "delete"]:
        assert getattr(client, method)("/action-items", headers=headers).status_code == 405


def test_revocation_removes_rows_on_next_request(api):
    client, db, headers = api
    assert titles(client.get("/action-items", headers=headers)) == {"Budget"}
    statement = db.execute.await_args.args[0]
    # Update the same isolated database through the synchronous session behind execute.
    session = db.execute.side_effect.__self__
    participant = session.query(MeetingParticipant).join(Meeting).filter(Meeting.title == "Budget").one()
    participant.access_type = "revoked"
    session.commit()
    assert titles(client.get("/action-items", headers=headers)) == set()
    assert statement.is_select
