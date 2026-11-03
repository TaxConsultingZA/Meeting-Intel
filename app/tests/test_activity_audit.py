"""Audit additions: isolated SQL; no external AI, email or Graph."""
from uuid import uuid4
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models import AuditEvent
from app.services.activity_audit import add_activity
from app.services.audit_queries import safe_metadata
from app.tests.test_meeting_decisions import decisions_api


def test_activity_commit_rollback_and_safe_identity():
    engine = create_engine("sqlite://")
    AuditEvent.__table__.create(engine)
    meeting = uuid4()
    with Session(engine) as db:
        event = add_activity(db, meeting_id=meeting, upn="Admin@Example.test",
            action="access.revoked", target_upn="Viewer@Example.test")
        assert event.resource_id == event.meeting_id == meeting
        assert event.actor_upn == "admin@example.test"
        assert event.event_metadata == safe_metadata(event.event_metadata)
        assert "viewer@" not in str(event.event_metadata)
        db.flush(); db.rollback()
        assert db.scalars(select(AuditEvent)).all() == []
        add_activity(db, meeting_id=meeting, upn="admin@example.test", action="meeting.viewed")
        db.commit()
        saved = db.scalar(select(AuditEvent))
        assert saved.occurred_at and saved.event_key and saved.correlation_id
    engine.dispose()


def test_manual_edit_is_atomic_and_read_has_no_delivery(decisions_api, monkeypatch):
    client, session, meeting, participant, actor, db = decisions_api
    url = f"/reviews/{meeting.id}/decisions"
    response = client.put(url, json={"decisions":[{"content":"PRIVATE DECISION", "decision_date":"2026-11-03"}]})
    assert response.status_code == 200
    events = session.scalars(select(AuditEvent)).all()
    assert [e.event_type for e in events] == ["meeting.decisions_saved"]
    assert "PRIVATE" not in str(events[0].event_metadata)
    before = len(events)
    assert client.put(url, json={"decisions":[{"id":str(uuid4()), "content":"PRIVATE", "decision_date":"2026-11-03"}]}).status_code == 422
    assert len(session.scalars(select(AuditEvent)).all()) == before
    from unittest.mock import AsyncMock
    monkeypatch.setattr("app.api.reviews._authorize", AsyncMock(return_value=meeting))
    response = client.get(f"/reviews/{meeting.id}/email-preview")
    assert response.status_code == 200
    assert session.scalars(select(AuditEvent)).all()[-1].event_type == "email.previewed"
    assert meeting.email_delivery_status is None


def test_reserved_accepted_and_unknown_never_mix():
    from app.tests.test_processing_monitor import job, event
    from app.services.processing_monitor import project_job
    reserved, unknown, accepted = event("provider.reserved"), event("provider.submission_unknown"), event("provider.submitted")
    reserved.outcome, unknown.outcome = "requested", "unknown"
    for events in ([reserved], [unknown], [reserved, unknown], []):
        result = project_job(job(), events)
        assert result["confirmed_submissions"] is None
        assert result["actual_cost"] is result["estimated_cost"] is None
    assert project_job(job(), [reserved, unknown, accepted, accepted])["confirmed_submissions"] == 1
    assert project_job(job(provider_status="poll_unknown"), [accepted])["confirmed_submissions"] == 1
