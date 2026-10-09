"""Reviewed action rows drive real preview rendering and the approval payload."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import reviews
from app.models import Confidence, ProcessingState
from app.schemas import ActionItemEdit, ApproveMeetingIn


@pytest.fixture
def workflow(monkeypatch):
    actor = "owner@taxconsulting.co.za"
    meeting_id = uuid4()
    snapshot = {"action": "Original task", "assigned_to": "Original owner",
                "due_date": "30 June", "department": "Tax", "reason": "Filing"}
    item = SimpleNamespace(id=uuid4(), meeting_id=meeting_id, task="Original task",
        owner="Original owner", deadline_text="30 June", deadline_iso=None,
        confidence=Confidence.medium, source_quote="Original quote", raw=dict(snapshot),
        approved=False, edited_by=None)
    meeting = SimpleNamespace(id=meeting_id, title="Review meeting", organizer_upn=actor,
        summary="Meeting summary", extracted_json={"action_items": [dict(snapshot)]},
        action_items=[item], participants=[], attendees_raw=[actor],
        drive_item_id="real-item", state=ProcessingState.awaiting_review,
        email_delivery_status=None, email_delivery_fingerprint=None,
        email_delivery_error=None, email_delivery_attempts=0)
    db = MagicMock()
    db.get = AsyncMock(return_value=item)
    db.commit = AsyncMock()
    authorize = AsyncMock(return_value=meeting)
    monkeypatch.setattr(reviews, "_authorize", authorize)
    monkeypatch.setattr(reviews, "_is_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(reviews, "_email_audit_actor", AsyncMock(
        return_value={"actor_id": str(uuid4()), "actor_upn": actor, "actor_entra_oid": None}))
    monkeypatch.setattr(reviews.settings, "emails_enabled", True)
    send = AsyncMock()
    monkeypatch.setattr(reviews.graph, "send_mail", send)
    return SimpleNamespace(actor=actor, meeting=meeting, item=item, db=db,
                           send=send, authorize=authorize)


async def test_edit_invalidates_preview_and_fresh_preview_is_exact_send(workflow):
    w = workflow
    old = await reviews.email_preview(w.meeting.id, db=w.db, upn=w.actor,
                                     recipients=[w.actor])
    await reviews.edit_item(str(w.item.id), ActionItemEdit(
        task="Reviewed task", owner="Reviewed owner", deadline_iso="2026-07-15"),
        db=w.db, upn=w.actor)
    assert w.authorize.await_args.kwargs["for_update"] is True
    assert w.item.edited_by == w.actor
    assert w.item.raw["action"] == "Original task"
    assert w.meeting.extracted_json["action_items"][0]["action"] == "Original task"
    fresh = await reviews.email_preview(w.meeting.id, db=w.db, upn=w.actor,
                                       recipients=[w.actor])
    assert fresh.fingerprint != old.fingerprint
    assert "Reviewed task" in fresh.html and "Reviewed owner" in fresh.html
    assert "2026-07-15" in fresh.html and "Tax" in fresh.html
    assert "Original task" not in fresh.html and "Original owner" not in fresh.html
    assert "30 June" not in fresh.html
    w.db.commit.reset_mock()
    with pytest.raises(HTTPException) as exc:
        await reviews.approve(w.meeting.id, db=w.db, upn=w.actor,
            body=ApproveMeetingIn(recipients=[w.actor], expected_fingerprint=old.fingerprint))
    assert exc.value.status_code == 409
    w.send.assert_not_awaited()
    w.db.commit.assert_not_awaited()
    assert w.item.approved is False
    body = ApproveMeetingIn(recipients=[w.actor], expected_fingerprint=fresh.fingerprint)
    await reviews.approve(w.meeting.id, db=w.db, upn=w.actor, body=body)
    w.send.assert_awaited_once_with(reviews.settings.mail_sender_upn or w.actor,
                                  fresh.recipients, fresh.subject, fresh.html)
    assert w.item.approved is True and w.meeting.state == ProcessingState.sent
    result = await reviews.approve(w.meeting.id, db=w.db, upn=w.actor, body=body)
    assert result["already_sent"] is True
    assert w.send.await_count == 1


@pytest.mark.parametrize("status", ["sending", "sent"])
async def test_action_edit_cannot_change_claimed_delivery(workflow, status):
    w = workflow
    w.meeting.email_delivery_status = status
    with pytest.raises(HTTPException) as exc:
        await reviews.edit_item(str(w.item.id), ActionItemEdit(task="Too late"),
                                db=w.db, upn=w.actor)
    assert exc.value.status_code == 409
    assert w.item.task == "Original task" and w.item.edited_by is None
    assert w.authorize.await_args.kwargs["for_update"] is True
    w.db.commit.assert_not_awaited()


async def test_confirmed_failed_delivery_allows_correction(workflow):
    w = workflow
    w.meeting.email_delivery_status = "failed"
    await reviews.edit_item(str(w.item.id), ActionItemEdit(owner=None), db=w.db, upn=w.actor)
    preview = await reviews.email_preview(w.meeting.id, db=w.db, upn=w.actor, recipients=[])
    assert "Original owner" not in preview.html
    assert w.item.owner is None
