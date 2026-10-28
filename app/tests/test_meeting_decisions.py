"""Manual decisions: isolated local SQL, no mail, Graph or AI."""
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.api.deps import current_user
from app.api.reviews import router
from app.db import get_db


@pytest.fixture
def decisions_api():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    tables = [models.Meeting, models.MeetingParticipant, models.ActionItem]
    if hasattr(models, "MeetingDecision"):
        tables.append(models.MeetingDecision)
    for model in tables:
        model.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    actor = {"upn": "alice@example.test"}
    meeting = models.Meeting(drive_item_id="local-decisions", title="Local meeting",
        organizer_upn="alice@example.test", state=models.ProcessingState.awaiting_review, summary="Saved notes",
        transcript="Private transcript", extracted_json={"objective": "Keep old data"},
        recorded_at=datetime(2026, 10, 22, tzinfo=UTC))
    session.add(meeting)
    session.flush()
    participant = models.MeetingParticipant(meeting_id=meeting.id, user_upn="alice@example.test", access_type="participant")
    session.add(participant)
    session.commit()
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=session.scalar)
    db.scalars = AsyncMock(side_effect=session.scalars)
    db.execute = AsyncMock(side_effect=session.execute)
    db.add = session.add
    db.delete = AsyncMock(side_effect=session.delete)
    db.commit = AsyncMock(side_effect=session.commit)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: actor["upn"]
    with patch("app.api.reviews._is_admin", new=AsyncMock(return_value=False)), TestClient(app) as client:
        yield client, session, meeting, participant, actor, db
    session.close()
    engine.dispose()


def save(client, meeting, content="Adopt the budget", date="2026-10-22", id=None):
    entry = {"content": content, "decision_date": date}
    if id:
        entry["id"] = id
    return client.put(f"/reviews/{meeting.id}/decisions", json={"decisions": [entry]})


def test_create_edit_preserves_old_data_and_invalidates_approval_preview(decisions_api):
    from app.api.reviews import _email_fingerprint
    client, session, meeting, _, _, _ = decisions_api
    first = save(client, meeting)
    assert first.status_code == 200
    item = first.json()[0]
    assert item["meeting_id"] == str(meeting.id)
    assert item["decision_date"] == "2026-10-22"
    revision = meeting.extracted_json["manual_decisions_revision"]
    old_fingerprint = _email_fingerprint(meeting.id, [], "subject", "html", decision_revision=revision)
    edited = save(client, meeting, "Approve revised budget", id=item["id"])
    assert edited.status_code == 200
    assert edited.json()[0]["id"] == item["id"]
    assert client.get(f"/reviews/{meeting.id}/decisions").json() == edited.json()
    assert meeting.extracted_json["objective"] == "Keep old data"
    assert meeting.summary == "Saved notes" and meeting.transcript == "Private transcript"
    assert old_fingerprint != _email_fingerprint(meeting.id, [], "subject", "html",
        decision_revision=meeting.extracted_json["manual_decisions_revision"])
    session.expire_all()
    assert len(session.scalars(select(models.MeetingDecision)).all()) == 1


@pytest.mark.parametrize("state", [models.ProcessingState.approved, models.ProcessingState.sent])
def test_approved_notes_are_readonly_for_editor_and_visible_for_viewer(decisions_api, state):
    client, session, meeting, _participant, actor, db = decisions_api
    assert save(client, meeting).status_code == 200
    meeting.state = state
    session.commit()
    db.commit.reset_mock()
    assert save(client, meeting, "Overwrite locked notes").status_code == 409
    db.commit.assert_not_awaited()
    actor["upn"] = "viewer@example.test"
    session.add(models.MeetingParticipant(meeting_id=meeting.id, user_upn="viewer@example.test", access_type="shared"))
    session.commit()
    session.expire(meeting, ["participants"])
    assert client.get(f"/reviews/{meeting.id}/decisions").json()[0]["content"] == "Adopt the budget"


@pytest.mark.parametrize("access", ["request_view", "request_edit", "revoked", "outsider"])
def test_no_view_access_cannot_read_edit_or_search_decisions(decisions_api, access):
    client, session, meeting, participant, actor, _ = decisions_api
    assert save(client, meeting).status_code == 200
    meeting.state = models.ProcessingState.approved
    meeting.organizer_upn = "other@example.test"
    participant.access_type = access if access != "outsider" else "participant"
    participant.edit_access_status = "approved"
    if access == "outsider":
        actor["upn"] = "outsider@example.test"
    session.commit()
    assert client.get(f"/reviews/{meeting.id}/decisions").status_code == 403
    assert save(client, meeting).status_code == 403
    response = client.get("/reviews/search?q=BUDGET")
    assert response.status_code == 200 and response.json() == []


def test_only_existing_note_editors_can_save_and_search_uses_decision_content(decisions_api):
    client, session, meeting, participant, _, _ = decisions_api
    meeting.organizer_upn = "other@example.test"
    session.commit()
    assert save(client, meeting).status_code == 403
    participant.edit_access_status = "approved"
    session.commit()
    assert save(client, meeting).status_code == 200
    meeting.state = models.ProcessingState.approved
    session.commit()
    response = client.get("/reviews/search?q=bUdGeT")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [str(meeting.id)]
    assert response.json()[0]["matched_decisions"] is True
    assert client.get("/reviews/search?q=Private").json() == []


def test_decision_search_only_indexes_approved_authorised_records(decisions_api):
    client, session, meeting, participant, _, _ = decisions_api
    assert save(client, meeting, content="Decision-only searchable phrase").status_code == 200
    assert client.get("/reviews/search?q=searchable").json() == []
    for state in [models.ProcessingState.approved, models.ProcessingState.sent]:
        meeting.state = state
        session.commit()
        rows = client.get("/reviews/search?q=searchable").json()
        assert [row["id"] for row in rows] == [str(meeting.id)]
        assert rows[0]["matched_decisions"] is True
        assert set(rows[0]) == {"id", "title", "recorded_at", "matched_summary", "matched_action_items", "matched_decisions"}
    participant.access_type = "request_view"
    participant.edit_access_status = "denied"
    session.commit()
    assert client.get(f"/reviews/{meeting.id}/decisions").status_code == 403
    assert client.get("/reviews/search?q=searchable").json() == []


def test_empty_validation_and_email_claim_lock(decisions_api):
    client, session, meeting, _, _, _ = decisions_api
    assert client.get(f"/reviews/{meeting.id}/decisions").json() == []
    assert save(client, meeting, content="  ").status_code == 422
    assert save(client, meeting, date="2026-02-30").status_code == 422
    meeting.email_delivery_status = "sending"
    session.commit()
    assert save(client, meeting).status_code == 409


async def test_decision_edit_rejects_a_previously_rendered_approval(decisions_api):
    from fastapi import HTTPException

    from app.api import reviews
    from app.schemas import ApproveMeetingIn

    client, session, meeting, _, _, db = decisions_api
    with patch.object(reviews, "build_meeting_email", return_value=("Subject", "Body")), \
         patch.object(reviews.graph, "send_mail", new=AsyncMock()) as send_mail:
        preview = await reviews.email_preview(meeting.id, db=db, upn=meeting.organizer_upn, recipients=[])
        assert save(client, meeting).status_code == 200
        db.commit.reset_mock()
        with pytest.raises(HTTPException) as failure:
            await reviews.approve(meeting.id, db=db, upn=meeting.organizer_upn,
                body=ApproveMeetingIn(recipients=[], expected_fingerprint=preview.fingerprint))
        assert failure.value.status_code == 409
        send_mail.assert_not_awaited()
        db.commit.assert_not_awaited()
        fresh = await reviews.email_preview(meeting.id, db=db, upn=meeting.organizer_upn, recipients=[])
        assert fresh.fingerprint != preview.fingerprint
        with patch.object(reviews, "_email_audit_actor", new=AsyncMock(return_value={})), \
             patch.object(reviews, "add_email_event"):
            result = await reviews.approve(meeting.id, db=db, upn=meeting.organizer_upn,
                body=ApproveMeetingIn(recipients=[], expected_fingerprint=fresh.fingerprint))
        assert result["state"] == models.ProcessingState.approved
        assert session.scalar(select(models.MeetingDecision.content)) == "Adopt the budget"
        assert meeting.summary == "Saved notes" and meeting.transcript == "Private transcript"
        assert save(client, meeting, "Overwrite after approval").status_code == 409
        send_mail.assert_not_awaited()


def test_decision_ids_and_limit_cannot_cross_meetings_and_saves_lock_parent(decisions_api):
    from uuid import uuid4

    from sqlalchemy.dialects import postgresql

    client, _, meeting, _, _, db = decisions_api
    assert save(client, meeting).status_code == 200
    sql = str(db.scalar.await_args.args[0].compile(dialect=postgresql.dialect())).upper()
    assert "FOR UPDATE" in sql
    db.commit.reset_mock()
    assert save(client, meeting, id=str(uuid4())).status_code == 422
    db.commit.assert_not_awaited()
    entry = {"content": "Budget", "decision_date": "2026-10-22"}
    assert client.put(f"/reviews/{meeting.id}/decisions", json={"decisions": [entry] * 51}).status_code == 422
    assert client.put(f"/reviews/{meeting.id}/decisions", json={"decisions": []}).json() == []
    assert client.get(f"/reviews/{meeting.id}/decisions").json() == []


def test_migration_upgrade_and_rollback_keep_existing_notes():
    path = Path(__file__).parents[2] / "alembic/versions/51d8f2a7c903_add_meeting_decisions.py"
    spec = importlib.util.spec_from_file_location("decision_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        models.Meeting.__table__.create(connection)
        models.ActionItem.__table__.create(connection)
        id = connection.execute(models.Meeting.__table__.insert().values(drive_item_id="legacy",
            summary="Legacy notes", extracted_json={"summary": "Legacy extraction"}).returning(models.Meeting.id)).scalar_one()
        connection.execute(models.ActionItem.__table__.insert().values(meeting_id=id, task="Legacy action"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            assert "meeting_decisions" in inspect(connection).get_table_names()
            migration.downgrade()
            assert "meeting_decisions" not in inspect(connection).get_table_names()
        row = connection.execute(select(models.Meeting.summary, models.Meeting.extracted_json)).one()
        assert row == ("Legacy notes", {"summary": "Legacy extraction"})
        assert connection.scalar(select(models.ActionItem.task)) == "Legacy action"
    engine.dispose()


@pytest.mark.parametrize("state", [models.ProcessingState.awaiting_review, models.ProcessingState.approved])
def test_admin_decisions_reuse_review_permissions_and_state_lock(decisions_api, state):
    client, session, meeting, _, actor, _ = decisions_api
    assert save(client, meeting).status_code == 200
    meeting.state = state
    session.commit()
    actor["upn"] = "admin@example.test"
    with patch("app.api.reviews._is_admin", new=AsyncMock(return_value=True)):
        assert client.get(f"/reviews/{meeting.id}/decisions").status_code == 200
        response = save(client, meeting, "Admin revised decision")
        assert response.status_code == (200 if state == models.ProcessingState.awaiting_review else 409)


def test_duplicate_decision_ids_rejected_without_changing_saved_review(decisions_api):
    client, session, meeting, _, _, db = decisions_api
    row = save(client, meeting).json()[0]
    db.commit.reset_mock()
    payload = {key: row[key] for key in ("id", "content", "decision_date")}
    assert client.put(f"/reviews/{meeting.id}/decisions", json={"decisions": [payload, payload]}).status_code == 422
    db.commit.assert_not_awaited()
    assert session.scalar(select(models.MeetingDecision.content)) == "Adopt the budget"
    assert meeting.extracted_json["objective"] == "Keep old data"


def test_decisions_migration_extends_the_deployed_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["51d8f2a7c903"]
    revisions = list(scripts.iterate_revisions("heads", "81c5f02a9d31"))
    assert [revision.revision for revision in revisions] == ["51d8f2a7c903"]
    assert revisions[0].down_revision == "81c5f02a9d31"
