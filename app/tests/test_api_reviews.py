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


class TestEditAccessWorkflow:
    @staticmethod
    def _meeting(*, access_type="participant", status="none"):
        from app.models import ProcessingState

        participant = MagicMock(
            user_upn="guest@taxconsulting.co.za",
            is_organizer=False,
            access_type=access_type,
            edit_access_status=status,
            edit_requested_at=None,
            edit_decided_at=None,
            edit_decided_by=None,
        )
        meeting = MagicMock(
            id="meeting-1",
            organizer_upn="owner@taxconsulting.co.za",
            attendees_raw=["owner@taxconsulting.co.za", "guest@taxconsulting.co.za"],
            participants=[participant],
            state=ProcessingState.awaiting_review,
        )
        return meeting, participant

    async def test_real_attendee_can_request_access(self, monkeypatch):
        from app.api import reviews

        meeting, participant = self._meeting()
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        result = await reviews.request_edit_access(
            "meeting-1", db=db, upn="guest@taxconsulting.co.za"
        )

        assert result == {"ok": True, "status": "pending"}
        assert participant.edit_access_status == "pending"
        assert participant.edit_requested_at is not None
        db.commit.assert_awaited_once()

    async def test_shared_viewer_who_did_not_attend_cannot_request(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews

        meeting, _ = self._meeting(access_type="shared")
        meeting.attendees_raw = ["owner@taxconsulting.co.za"]
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        with pytest.raises(HTTPException) as exc:
            await reviews.request_edit_access(
                "meeting-1", db=db, upn="guest@taxconsulting.co.za"
            )

        assert exc.value.status_code == 403
        db.commit.assert_not_awaited()

    async def test_pending_request_is_idempotent(self, monkeypatch):
        from app.api import reviews

        meeting, _ = self._meeting(status="pending")
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        result = await reviews.request_edit_access(
            "meeting-1", db=db, upn="guest@taxconsulting.co.za"
        )

        assert result["status"] == "pending"
        db.commit.assert_not_awaited()

    async def test_organizer_can_approve_pending_request(self, monkeypatch):
        from app.api import reviews
        from app.schemas import EditAccessDecisionIn

        meeting, participant = self._meeting(status="pending")
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        result = await reviews.decide_edit_access(
            "meeting-1", "guest@taxconsulting.co.za",
            EditAccessDecisionIn(approved=True), db=db,
            upn="owner@taxconsulting.co.za",
        )

        assert result["status"] == "approved"
        assert participant.edit_decided_by == "owner@taxconsulting.co.za"
        db.commit.assert_awaited_once()

    async def test_organizer_can_reject_pending_request(self, monkeypatch):
        from app.api import reviews
        from app.schemas import EditAccessDecisionIn

        meeting, participant = self._meeting(status="pending")
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        result = await reviews.decide_edit_access(
            "meeting-1", "guest@taxconsulting.co.za",
            EditAccessDecisionIn(approved=False), db=db,
            upn="owner@taxconsulting.co.za",
        )

        assert result["status"] == "denied"
        assert participant.edit_access_status == "denied"

    async def test_organizer_cannot_approve_without_pending_request(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import EditAccessDecisionIn

        meeting, _ = self._meeting(status="none")
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        with pytest.raises(HTTPException) as exc:
            await reviews.decide_edit_access(
                "meeting-1", "guest@taxconsulting.co.za",
                EditAccessDecisionIn(approved=True), db=db,
                upn="owner@taxconsulting.co.za",
            )

        assert exc.value.status_code == 409
        db.commit.assert_not_awaited()

    async def test_non_organizer_cannot_decide_request(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import EditAccessDecisionIn

        meeting, _ = self._meeting(status="pending")
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        with pytest.raises(HTTPException) as exc:
            await reviews.decide_edit_access(
                "meeting-1", "guest@taxconsulting.co.za",
                EditAccessDecisionIn(approved=True), db=AsyncMock(),
                upn="guest@taxconsulting.co.za",
            )

        assert exc.value.status_code == 403

    async def test_approved_attendee_can_edit_transcript(self, monkeypatch):
        from app.api import reviews
        from app.schemas import TranscriptEdit

        meeting, _ = self._meeting(status="approved")
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        result = await reviews.edit_transcript(
            "meeting-1", TranscriptEdit(transcript="Updated"), db=db,
            upn="guest@taxconsulting.co.za",
        )

        assert result == {"ok": True}
        assert meeting.transcript == "Updated"
        db.commit.assert_awaited_once()

    async def test_unapproved_attendee_cannot_edit_transcript(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import TranscriptEdit

        meeting, _ = self._meeting(status="pending")
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        with pytest.raises(HTTPException) as exc:
            await reviews.edit_transcript(
                "meeting-1", TranscriptEdit(transcript="Bypass"), db=db,
                upn="guest@taxconsulting.co.za",
            )

        assert exc.value.status_code == 403
        db.commit.assert_not_awaited()

    async def test_approved_attendee_cannot_approve_or_group_email(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import ApproveMeetingIn

        meeting, _ = self._meeting(status="approved")
        meeting.action_items = []
        db = AsyncMock()
        send_mail = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        monkeypatch.setattr(reviews.graph, "send_mail", send_mail)

        with pytest.raises(HTTPException) as exc:
            await reviews.approve(
                "meeting-1", db=db, upn="guest@taxconsulting.co.za",
                body=ApproveMeetingIn(recipients=[
                    "owner@taxconsulting.co.za", "guest@taxconsulting.co.za"
                ]),
            )

        assert exc.value.status_code == 403
        send_mail.assert_not_awaited()
        db.commit.assert_not_awaited()


class TestSpeakerSamples:
    @staticmethod
    def _meeting():
        meeting = MagicMock()
        meeting.organizer_upn = "owner@taxconsulting.co.za"
        meeting.participants = []
        meeting.extracted_json = {
            "transcript_segments": [
                {"speaker": "Speaker A", "text": "Short", "start": 2.0, "end": 4.0},
                {"speaker": "Speaker A", "text": "Representative", "start": 10.0, "end": 30.0},
                {"speaker": "Speaker B", "text": "Other", "start": 31.0, "end": 35.0},
            ]
        }
        return meeting

    def test_uses_longest_segment_and_caps_sample_at_twelve_seconds(self):
        from app.api.reviews import _speaker_sample_window

        assert _speaker_sample_window(self._meeting(), "speaker a") == (9.75, 21.75)

    def test_unknown_speaker_has_no_sample(self):
        from app.api.reviews import _speaker_sample_window

        assert _speaker_sample_window(self._meeting(), "Speaker C") is None

    async def test_non_organizer_cannot_fetch_sample(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews

        meeting = self._meeting()
        meeting.participants = [
            MagicMock(user_upn="guest@taxconsulting.co.za", is_organizer=False)
        ]
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        build_sample = AsyncMock(return_value=b"audio")
        monkeypatch.setattr(reviews, "_build_speaker_sample", build_sample)

        with pytest.raises(HTTPException) as exc:
            await reviews.speaker_sample(
                "meeting-1", "Speaker A", db=AsyncMock(),
                upn="guest@taxconsulting.co.za",
            )

        assert exc.value.status_code == 403
        build_sample.assert_not_awaited()


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

    async def test_local_test_meeting_never_sends_real_email(self, monkeypatch):
        from app.api import reviews
        from app.schemas import ApproveMeetingIn
        from app.models import ProcessingState

        meeting = self._meeting()
        meeting.drive_item_id = "meeting-intel-test-t2-speaker-audio"
        meeting.extracted_json = {"local_test_data": True}
        db = AsyncMock()
        send_mail = AsyncMock()
        monkeypatch.setattr(reviews.settings, "emails_enabled", True)
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        monkeypatch.setattr(reviews, "build_meeting_email", lambda _: ("Subject", "Body"))
        monkeypatch.setattr(reviews.graph, "send_mail", send_mail)

        result = await reviews.approve(
            "meeting-1", db=db, upn="owner@taxconsulting.co.za",
            body=ApproveMeetingIn(recipients=["guest@taxconsulting.co.za"]),
        )

        assert result["state"] == ProcessingState.approved
        send_mail.assert_not_awaited()


class TestApprovedAttendeeSelfCopy:
    @staticmethod
    def _meeting(status="approved"):
        from app.models import ProcessingState

        participant = MagicMock(
            user_upn="guest@taxconsulting.co.za",
            is_organizer=False,
            access_type="participant",
            edit_access_status=status,
        )
        meeting = MagicMock(
            id="meeting-1",
            organizer_upn="owner@taxconsulting.co.za",
            attendees_raw=["owner@taxconsulting.co.za", "guest@taxconsulting.co.za"],
            participants=[participant],
            state=ProcessingState.sent,
        )
        return meeting

    @staticmethod
    def _db():
        db = MagicMock()
        db.commit = AsyncMock()
        return db

    async def test_direct_api_request_cannot_target_another_recipient(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import SendMeetingCopyIn

        meeting = self._meeting()
        db = self._db()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        send_mail = AsyncMock()
        monkeypatch.setattr(reviews.graph, "send_mail", send_mail)

        with pytest.raises(HTTPException) as exc:
            await reviews.send_copy_to_self(
                "meeting-1",
                SendMeetingCopyIn(recipient_upn="other@taxconsulting.co.za"),
                db=db,
                upn="guest@taxconsulting.co.za",
            )

        assert exc.value.status_code == 403
        send_mail.assert_not_awaited()
        db.add.assert_not_called()

    async def test_unapproved_attendee_cannot_send_copy(self, monkeypatch):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import SendMeetingCopyIn

        meeting = self._meeting(status="pending")
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        with pytest.raises(HTTPException) as exc:
            await reviews.send_copy_to_self(
                "meeting-1",
                SendMeetingCopyIn(recipient_upn="guest@taxconsulting.co.za"),
                db=self._db(),
                upn="guest@taxconsulting.co.za",
            )

        assert exc.value.status_code == 403

    async def test_sends_only_to_caller_and_records_audit(self, monkeypatch):
        from app.api import reviews
        from app.schemas import SendMeetingCopyIn

        meeting = self._meeting()
        db = self._db()
        send_mail = AsyncMock()
        monkeypatch.setattr(reviews.settings, "emails_enabled", True)
        monkeypatch.setattr(reviews.settings, "mail_sender_upn", "notes@taxconsulting.co.za")
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        monkeypatch.setattr(reviews, "build_meeting_email", lambda _: ("Subject", "Body"))
        monkeypatch.setattr(reviews.graph, "send_mail", send_mail)

        result = await reviews.send_copy_to_self(
            "meeting-1",
            SendMeetingCopyIn(recipient_upn=" GUEST@taxconsulting.co.za "),
            db=db,
            upn="guest@taxconsulting.co.za",
        )

        assert result == {"ok": True, "sent": True}
        send_mail.assert_awaited_once_with(
            "notes@taxconsulting.co.za", ["guest@taxconsulting.co.za"], "Subject", "Body"
        )
        audit = db.add.call_args.args[0]
        assert audit.actor_upn == "guest@taxconsulting.co.za"
        assert audit.recipient_upn == "guest@taxconsulting.co.za"
        assert audit.status == "sent"
        assert db.commit.await_count == 2

    async def test_local_test_meeting_never_sends_self_copy(self, monkeypatch):
        from app.api import reviews
        from app.schemas import SendMeetingCopyIn

        meeting = self._meeting()
        meeting.drive_item_id = "meeting-intel-test-t3-self-copy"
        meeting.extracted_json = {"local_test_data": True}
        db = self._db()
        send_mail = AsyncMock()
        monkeypatch.setattr(reviews.settings, "emails_enabled", True)
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        monkeypatch.setattr(reviews.graph, "send_mail", send_mail)

        result = await reviews.send_copy_to_self(
            "meeting-1",
            SendMeetingCopyIn(recipient_upn="guest@taxconsulting.co.za"),
            db=db,
            upn="guest@taxconsulting.co.za",
        )

        assert result == {"ok": True, "sent": False}
        assert db.add.call_args.args[0].status == "disabled"
        send_mail.assert_not_awaited()
