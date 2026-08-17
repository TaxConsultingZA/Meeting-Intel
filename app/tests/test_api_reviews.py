"""Tests for app/api/reviews.py — domain validation and endpoint behaviour (mocked DB)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials


def _make_app():
    """Build a minimal FastAPI app with only the reviews router for isolation."""
    from fastapi import FastAPI
    from app.api.reviews import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestCurrentUser:
    async def test_valid_domain_accepted(self):
        from app.api.reviews import current_user
        result = await current_user(
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="mock:alice@taxconsulting.co.za"
            )
        )
        assert result == "alice@taxconsulting.co.za"

    async def test_outside_domain_raises_403(self):
        from fastapi import HTTPException
        from app.api.reviews import current_user
        with pytest.raises(HTTPException) as exc_info:
            await current_user(
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer", credentials="mock:alice@otherdomain.com"
                )
            )
        assert exc_info.value.status_code == 403

    def test_missing_bearer_token_raises_401(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/reviews/all")
        assert resp.status_code == 401

    def test_spoofable_identity_header_is_rejected(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/reviews/all",
            headers={"x-user-upn": "alice@taxconsulting.co.za"},
        )
        assert resp.status_code == 401


class TestAllMeetingsEndpoint:
    def test_returns_empty_list_when_no_meetings(self):
        from app.db import get_db
        app = _make_app()

        async def override_db():
            mock_session = AsyncMock()
            mock_session.scalars = AsyncMock(return_value=MagicMock(unique=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
            yield mock_session

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        resp = client.get(
            "/reviews/all",
            headers={"Authorization": "Bearer mock:alice@taxconsulting.co.za"},
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestToOut:
    def test_converts_meeting_to_output(self):
        from app.api.reviews import _to_out
        from app.models import ProcessingState
        m = MagicMock()
        m.id = "uuid-1"
        m.title = "Budget Meeting"
        m.state = ProcessingState.awaiting_review
        m.summary = "Summary here"
        m.transcript = "Speaker A: Opening remarks"
        m.organizer_upn = "organiser@taxconsulting.co.za"
        m.extracted_json = None
        m.error = None
        m.attendees_raw = []
        m.approved_recipients = []
        m.participants = []
        m.action_items = []
        out = _to_out(m)
        assert out.id == "uuid-1"
        assert out.title == "Budget Meeting"
        assert out.state == ProcessingState.awaiting_review
        assert out.transcript == "Speaker A: Opening remarks"


class TestOrganizerReviewGate:
    def test_organizer_is_allowed(self):
        from app.api.reviews import _require_organizer

        meeting = MagicMock()
        meeting.organizer_upn = "owner@taxconsulting.co.za"
        meeting.participants = []
        _require_organizer(meeting, "owner@taxconsulting.co.za")

    def test_non_organizer_is_rejected(self):
        from fastapi import HTTPException
        from app.api.reviews import _require_organizer

        meeting = MagicMock()
        meeting.organizer_upn = "owner@taxconsulting.co.za"
        meeting.participants = [
            MagicMock(user_upn="guest@taxconsulting.co.za", is_organizer=False)
        ]
        with pytest.raises(HTTPException) as exc:
            _require_organizer(meeting, "guest@taxconsulting.co.za")
        assert exc.value.status_code == 403


class TestReviewStateGate:
    def test_awaiting_review_is_editable(self):
        from app.api.reviews import _require_awaiting_review
        from app.models import ProcessingState

        meeting = MagicMock(state=ProcessingState.awaiting_review)
        _require_awaiting_review(meeting)

    @pytest.mark.parametrize(
        "state",
        ["approved", "completed", "processing", "failed"],
    )
    def test_other_states_are_locked(self, state):
        from fastapi import HTTPException
        from app.api.reviews import _require_awaiting_review

        meeting = MagicMock(state=state)
        with pytest.raises(HTTPException) as exc:
            _require_awaiting_review(meeting)
        assert exc.value.status_code == 409


class TestApprovalDelivery:
    @staticmethod
    def _meeting():
        from app.models import ProcessingState

        meeting = MagicMock()
        meeting.organizer_upn = "owner@taxconsulting.co.za"
        meeting.attendees_raw = ["guest@taxconsulting.co.za"]
        meeting.participants = []
        meeting.action_items = [MagicMock(approved=False)]
        meeting.state = ProcessingState.awaiting_review
        meeting.id = "meeting-1"
        meeting.email_delivery_status = None
        meeting.email_delivery_fingerprint = None
        meeting.email_delivery_error = None
        meeting.email_delivery_attempts = 0
        return meeting

    async def test_mail_failure_remains_retryable(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import ApproveMeetingIn
        from app.models import ProcessingState

        meeting = self._meeting()
        db = AsyncMock()
        monkeypatch.setattr(reviews.settings, "emails_enabled", True)
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        monkeypatch.setattr(reviews, "build_meeting_email", lambda _: ("Subject", "Body"))
        monkeypatch.setattr(reviews.graph, "send_mail", AsyncMock(side_effect=RuntimeError("Graph failed")))

        with pytest.raises(HTTPException) as exc:
            await reviews.approve(
                "meeting-1",
                db=db,
                upn="owner@taxconsulting.co.za",
                body=ApproveMeetingIn(recipients=["guest@taxconsulting.co.za"]),
            )

        assert exc.value.status_code == 502
        assert meeting.state == ProcessingState.awaiting_review
        assert meeting.action_items[0].approved is False
        assert meeting.email_delivery_status == "failed"
        assert meeting.email_delivery_attempts == 1
        assert "Graph failed" in meeting.email_delivery_error
        assert db.commit.await_count == 2

    async def test_successful_mail_and_approval_commit_together(self, monkeypatch):
        from app.api import reviews
        from app.schemas import ApproveMeetingIn
        from app.models import ProcessingState

        meeting = self._meeting()
        db = AsyncMock()
        send_mail = AsyncMock()
        monkeypatch.setattr(reviews.settings, "emails_enabled", True)
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        monkeypatch.setattr(reviews, "build_meeting_email", lambda _: ("Subject", "Body"))
        monkeypatch.setattr(reviews.graph, "send_mail", send_mail)

        result = await reviews.approve(
            "meeting-1",
            db=db,
            upn="owner@taxconsulting.co.za",
            body=ApproveMeetingIn(recipients=["guest@taxconsulting.co.za"]),
        )

        assert result["state"] == ProcessingState.sent
        assert meeting.action_items[0].approved is True
        send_mail.assert_awaited_once()
        assert meeting.email_delivery_status == "sent"
        assert meeting.email_delivery_attempts == 1
        assert db.commit.await_count == 2

    async def test_sending_state_blocks_ambiguous_resend(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import ApproveMeetingIn

        meeting = self._meeting()
        meeting.email_delivery_status = "sending"
        db = AsyncMock()
        monkeypatch.setattr(reviews.settings, "emails_enabled", True)
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        monkeypatch.setattr(reviews, "build_meeting_email", lambda _: ("Subject", "Body"))
        send_mail = AsyncMock()
        monkeypatch.setattr(reviews.graph, "send_mail", send_mail)

        with pytest.raises(HTTPException) as exc:
            await reviews.approve(
                "meeting-1", db=db, upn="owner@taxconsulting.co.za",
                body=ApproveMeetingIn(recipients=["guest@taxconsulting.co.za"]),
            )

        assert exc.value.status_code == 409
        send_mail.assert_not_awaited()
