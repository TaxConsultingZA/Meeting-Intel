import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app import models
from app.api.deps import require_registered
from app.api.meeting_insights import router
from app.db import get_db
@pytest.fixture
def insights_api():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    tables = [models.Meeting, models.MeetingParticipant, models.ActionItem, models.MeetingInsightDraft]
    if hasattr(models, "MeetingDecision"):
        tables.append(models.MeetingDecision)
    for model in tables:
        model.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    actor = {"upn": "alice@example.test"}
    meeting = models.Meeting(drive_item_id="local-decisions", title="Local meeting",
        organizer_upn="alice@example.test", state=models.ProcessingState.awaiting_review, summary="Saved notes",
        transcript="[A] We will prepare a demo.\n[B] 请跟进测试。\n[A] We agreed to use mock.\n[B] 决定先本地审核。", extracted_json={"objective": "Keep old data"},
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
    db.get = AsyncMock(side_effect=session.get)
    db.add = session.add
    db.delete = AsyncMock(side_effect=session.delete)
    db.commit = AsyncMock(side_effect=session.commit)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_registered] = lambda: actor["upn"]
    with patch("app.api.meeting_insights._is_admin", new=AsyncMock(return_value=False)), TestClient(app) as client:
        yield client, session, meeting, participant, actor, db
    session.close()
    engine.dispose()

def test_generate_edit_confirm_idempotency_and_evidence(insights_api):
    client, session, meeting, _, _, db = insights_api
    url = f"/reviews/{meeting.id}/insights"
    original = (meeting.transcript, meeting.summary, meeting.state, meeting.extracted_json)
    draft = client.post(url).json()
    assert draft["status"] == "awaiting_review"
    assert len(draft["actions"]) == 2 and len(draft["decisions"]) == 2
    assert all(i["source_quote"] in meeting.transcript and i["owner"] is None and i["deadline"] is None for i in draft["actions"])
    assert session.scalars(select(models.ActionItem)).all() == []
    assert client.post(url).json() == draft
    draft["summary"] = "Human summary"
    draft["actions"][0]["text"] = "Reviewed demo task"
    draft["actions"][0]["status"] = "confirmed"
    result = client.put(url, json=draft)
    assert result.status_code == 200
    assert client.put(url, json=draft).status_code == 409
    assert client.post(url).json()["summary"] == "Human summary"
    items = session.scalars(select(models.ActionItem)).all()
    assert len(items) == 1 and items[0].approved and items[0].source_quote == draft["actions"][0]["source_quote"]
    assert (meeting.transcript, meeting.summary, meeting.state, meeting.extracted_json) == original
    assert client.get(url).json()["version"] == 2
    bad = result.json(); bad["actions"][1]["source_quote"] = "forged"
    assert client.put(url, json=bad).status_code == 422
    bad = result.json(); bad["actions"][0]["text"] = "overwrite confirmed"
    assert client.put(url, json=bad).status_code == 409
    meeting.transcript += " changed"; session.commit()
    assert client.put(url, json=result.json()).status_code == 409

@pytest.mark.parametrize("error", [RuntimeError("secret"), asyncio.TimeoutError()])
def test_failure_retry_does_not_change_transcript(insights_api, error):
    client, session, meeting, _, _, _ = insights_api
    url = f"/reviews/{meeting.id}/insights"
    original = meeting.transcript
    with patch("app.services.meeting_insights.adapter.analyze", new=AsyncMock(side_effect=error)):
        result = client.post(url)
    assert result.status_code == 200 and result.json()["status"] == "failed"
    assert "secret" not in result.text
    assert meeting.transcript == original and meeting.state == models.ProcessingState.awaiting_review
    assert client.post(url).json()["status"] == "awaiting_review"

@pytest.mark.parametrize("access", ["shared", "request_view", "revoked", "outsider"])
def test_permissions(insights_api, access):
    client, session, meeting, participant, actor, _ = insights_api
    url = f"/reviews/{meeting.id}/insights"
    client.post(url)
    meeting.organizer_upn = "other@example.test"
    participant.access_type = access if access != "outsider" else "participant"
    if access == "outsider": actor["upn"] = "outsider@example.test"
    session.commit()
    assert client.get(url).status_code == (200 if access == "shared" else 403)
    assert client.post(url).status_code == 403
    assert client.put(url, json={"version":1,"summary":"", "actions":[],"decisions":[]}).status_code == 403

def test_empty_transcript(insights_api):
    client, session, meeting, *_ = insights_api
    meeting.transcript = " "; session.commit()
    assert client.post(f"/reviews/{meeting.id}/insights").status_code == 409

def test_migration_roundtrip(insights_api):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    _, session, meeting, *_ = insights_api
    path = Path("alembic/versions/62e9a3b8d014_meeting_insight_drafts.py")
    spec = importlib.util.spec_from_file_location("insight_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = session.get_bind()
    models.MeetingInsightDraft.__table__.drop(engine)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert "meeting_insight_drafts" in inspect(conn).get_table_names()
            migration.downgrade()
            assert "meeting_insight_drafts" not in inspect(conn).get_table_names()
    assert session.get(models.Meeting, meeting.id).transcript == meeting.transcript

def test_generation_and_review_lock_parent_row(insights_api):
    from sqlalchemy.dialects import postgresql
    client, _, meeting, _, _, db = insights_api
    url = f"/reviews/{meeting.id}/insights"
    draft = client.post(url).json()
    client.put(url, json=draft)
    queries = [str(call.args[0].compile(dialect=postgresql.dialect())) for call in db.scalar.call_args_list]
    assert len(queries) == 2
    assert all("FOR UPDATE" in q and "meetings.id" in q for q in queries)
