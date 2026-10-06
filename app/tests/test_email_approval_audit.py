"""Email audit attribution, transaction ordering, and safe submission outcomes."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.api import reviews
from app.models import AuditEvent, ProcessingState
from app.schemas import ApproveMeetingIn


@pytest.fixture
def workflow(monkeypatch):
    actor = SimpleNamespace(id=uuid4(), upn="owner@example.test", entra_oid="owner-oid")
    meeting = SimpleNamespace(id=uuid4(), organizer_upn=actor.upn,
        attendees_raw=["guest@example.test"], participants=[],
        action_items=[SimpleNamespace(approved=False)], state=ProcessingState.awaiting_review,
        email_delivery_status=None, email_delivery_attempts=0, email_delivery_error=None,
        email_delivery_fingerprint=None, drive_item_id="real-item", extracted_json={})
    db = MagicMock()
    db.scalar = AsyncMock(return_value=actor)
    db.rollback = AsyncMock()
    pending, commits = [], []
    db.add.side_effect = pending.append

    async def commit():
        commits.append((meeting.email_delivery_status, meeting.state, list(pending)))
        pending.clear()

    db.commit = AsyncMock(side_effect=commit)
    monkeypatch.setattr(reviews, "_is_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
    monkeypatch.setattr(reviews, "build_meeting_email", lambda _: ("PRIVATE SUBJECT", "PRIVATE BODY"))
    monkeypatch.setattr(reviews.settings, "emails_enabled", True)
    send = AsyncMock()
    monkeypatch.setattr(reviews.graph, "send_mail", send)
    body = ApproveMeetingIn(recipients=["guest@example.test"],
        expected_fingerprint=reviews._email_fingerprint(meeting.id,
            ["guest@example.test"], "PRIVATE SUBJECT", "PRIVATE BODY"))
    return SimpleNamespace(actor=actor, meeting=meeting, db=db, commits=commits,
        pending=pending, send=send, body=body)


async def approve(w):
    return await reviews.approve(str(w.meeting.id), db=w.db, upn=w.actor.upn, body=w.body)


def events(w):
    return [event for _, _, batch in w.commits for event in batch]


async def test_success_commits_claim_then_send_and_approval(workflow):
    w = workflow

    async def submit(*args):
        assert len(w.commits) == 1
        assert w.commits[0][:2] == ("sending", ProcessingState.awaiting_review)
        assert not w.pending
        # Identity lookup must finish before the claim commit and Graph call.
        assert w.db.scalar.await_count == 1

    w.send.side_effect = submit
    await approve(w)
    assert len(w.commits) == 2
    claim, final = w.commits
    assert [e.event_type for e in claim[2]] == ["email.approval_requested"]
    assert [e.event_type for e in final[2]] == ["email.send", "email.approved"]
    assert final[:2] == ("sent", ProcessingState.sent)
    request, sent, approved = events(w)
    assert request.outcome == "requested"
    assert sent.outcome == approved.outcome == "succeeded"
    assert request.actor_id == approved.actor_id == str(w.actor.id)
    assert request.actor_upn == w.actor.upn and request.actor_entra_oid == "owner-oid"
    assert sent.actor_type == "system" and sent.actor_id == "email_sender"
    assert len({e.correlation_id for e in events(w)}) == 1
    assert len({e.event_key for e in events(w)}) == 3
    for event in events(w):
        assert isinstance(event, AuditEvent)
        assert event.meeting_id == event.resource_id == w.meeting.id
        assert event.resource_type == "meeting"
        assert event.event_metadata == {"attempt": 1, "fingerprint": w.body.expected_fingerprint,
            "recipient_count": 1, "email_category": "meeting_notes"}
    before = len(events(w))
    assert (await approve(w))["already_sent"] is True
    assert len(events(w)) == before
    w.send.assert_awaited_once()


@pytest.mark.parametrize("failure,outcome,status,category", [
    (httpx.HTTPStatusError("SECRET", request=httpx.Request("POST", "https://private.test"),
        response=httpx.Response(400)), "failed", "failed", "provider_rejected"),
    (httpx.ConnectTimeout("SECRET"), "failed", "failed", "connection_unavailable"),
    (httpx.ReadTimeout("SECRET"), "unknown", "sending", "submission_uncertain"),
    (httpx.WriteTimeout("SECRET"), "unknown", "sending", "submission_uncertain"),
    (httpx.HTTPStatusError("SECRET", request=httpx.Request("POST", "https://private.test"),
        response=httpx.Response(503)), "unknown", "sending", "submission_uncertain"),
    (RuntimeError("SECRET"), "unknown", "sending", "submission_uncertain"),
    (asyncio.CancelledError(), "unknown", "sending", "submission_uncertain"),
])
async def test_safe_failure_outcomes_share_state_commit(workflow, failure, outcome, status, category):
    w = workflow
    w.send.side_effect = failure
    with pytest.raises(asyncio.CancelledError if isinstance(failure, asyncio.CancelledError) else HTTPException):
        await approve(w)
    assert len(w.commits) == 2
    assert w.commits[1][:2] == (status, ProcessingState.awaiting_review)
    assert [(e.event_type, e.outcome) for e in events(w)] == [
        ("email.approval_requested", "requested"), ("email.send", outcome)]
    assert w.meeting.email_delivery_error == category
    assert events(w)[1].event_metadata["error_category"] == category
    assert "SECRET" not in repr([e.event_metadata for e in events(w)])
    assert not w.meeting.action_items[0].approved
    if outcome == "unknown":
        with pytest.raises(HTTPException) as exc:
            await approve(w)
        assert exc.value.status_code == 409
        assert len(w.commits) == 2
        w.send.assert_awaited_once()


@pytest.mark.parametrize("reason", ["no_recipients", "disabled", "local_test", "missing_organizer"])
async def test_no_send_has_only_durable_approval(workflow, monkeypatch, reason):
    w = workflow
    if reason == "no_recipients":
        w.body.recipients = []
    elif reason == "disabled":
        monkeypatch.setattr(reviews.settings, "emails_enabled", False)
    elif reason == "local_test":
        w.meeting.drive_item_id = "meeting-intel-test-fixture"
        w.meeting.extracted_json = {"local_test_data": True}
    else:
        w.meeting.organizer_upn = None
        w.meeting.participants = [SimpleNamespace(user_upn=w.actor.upn, is_organizer=True)]
    w.body.expected_fingerprint = reviews._email_fingerprint(w.meeting.id,
        w.body.recipients, "PRIVATE SUBJECT", "PRIVATE BODY")
    await approve(w)
    assert len(w.commits) == 1
    assert w.commits[0][:2] == ("not_required", ProcessingState.approved)
    assert [(e.event_type, e.outcome) for e in events(w)] == [("email.approved", "succeeded")]
    w.send.assert_not_awaited()


@pytest.mark.parametrize("gate", ["fingerprint", "permissions", "recipients", "state"])
async def test_rejected_request_has_no_events_or_commit(workflow, gate):
    w = workflow
    if gate == "fingerprint":
        w.body.expected_fingerprint = "stale"
    elif gate == "permissions":
        w.meeting.organizer_upn = "someone@example.test"
    elif gate == "recipients":
        w.body.recipients = ["outsider@example.test"]
    else:
        w.meeting.state = ProcessingState.approved
    with pytest.raises(HTTPException):
        await approve(w)
    assert not w.pending and not events(w)
    w.db.commit.assert_not_awaited()
    w.send.assert_not_awaited()


async def test_failed_claim_commit_never_submits(workflow):
    w = workflow
    w.db.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        await approve(w)
    w.send.assert_not_awaited()
    assert not events(w)


async def test_failed_final_commit_does_not_resubmit_or_claim_success(workflow):
    w = workflow
    original_commit = w.db.commit.side_effect

    async def commit():
        if w.commits:
            raise RuntimeError("final commit failed")
        await original_commit()

    w.db.commit.side_effect = commit
    with pytest.raises(RuntimeError):
        await approve(w)
    assert [(e.event_type, e.outcome) for e in events(w)] == [("email.approval_requested", "requested")]
    assert w.commits[0][0] == "sending"
    w.send.assert_awaited_once()


async def test_confirmed_failure_retry_uses_new_attempt_and_correlation(workflow):
    w = workflow
    w.send.side_effect = httpx.ConnectError("PRIVATE")
    with pytest.raises(HTTPException):
        await approve(w)
    first = events(w)[0].correlation_id
    w.send.side_effect = None
    await approve(w)
    assert len(events(w)) == 5
    assert events(w)[2].event_metadata["attempt"] == 2
    assert events(w)[2].correlation_id != first
    assert len({e.event_key for e in events(w)}) == 5


async def test_legacy_actor_keeps_permissions_without_registration(workflow):
    w = workflow
    w.db.scalar.return_value = None
    await approve(w)
    assert events(w)[0].actor_upn == w.actor.upn
    assert events(w)[0].actor_id == events(w)[2].actor_id
    assert events(w)[0].actor_entra_oid is None


async def test_admin_is_attributed_instead_of_meeting_organizer(workflow, monkeypatch):
    w = workflow
    w.actor.upn = "admin@example.test"
    monkeypatch.setattr(reviews, "_is_admin", AsyncMock(return_value=True))
    await approve(w)
    assert events(w)[0].actor_upn == events(w)[2].actor_upn == "admin@example.test"
    assert w.meeting.approved_by == "admin@example.test"


async def test_audit_staging_failure_prevents_send(workflow, monkeypatch):
    w = workflow
    monkeypatch.setattr(reviews, "add_email_event", MagicMock(side_effect=ValueError("audit rejected")))
    with pytest.raises(ValueError):
        await approve(w)
    w.db.commit.assert_not_awaited()
    w.send.assert_not_awaited()


async def test_terminal_audit_failure_leaves_only_durable_claim(workflow, monkeypatch):
    w = workflow
    original = reviews.add_email_event

    def stage(db, **kwargs):
        if kwargs["event_type"] == "email.send":
            raise ValueError("audit rejected")
        return original(db, **kwargs)

    monkeypatch.setattr(reviews, "add_email_event", stage)
    with pytest.raises(ValueError):
        await approve(w)
    assert w.commits[0][0] == "sending"
    assert len(w.commits) == 1
    assert len(events(w)) == 1
    w.send.assert_awaited_once()
