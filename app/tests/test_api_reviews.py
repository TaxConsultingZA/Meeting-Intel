"""Tests for app/api/reviews.py — domain validation and endpoint behaviour (mocked DB)."""
import pytest
from types import SimpleNamespace
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

    async def test_query_only_loads_columns_used_by_response(self):
        from sqlalchemy.dialects import postgresql
        from app.api import reviews

        db = AsyncMock()
        db.scalars.return_value = MagicMock(
            unique=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        assert await reviews.all_meetings(
            db=db, upn="alice@taxconsulting.co.za"
        ) == []

        statement = db.scalars.await_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "JOIN meeting_participants" in sql
        assert "lower(meeting_participants.user_upn)" in sql
        assert "meetings.transcript" not in sql
        assert "meetings.summary" not in sql
        assert "meetings.extracted_json" not in sql
        assert "meetings.drive_item_id" not in sql
        assert "meetings.email_delivery_error" not in sql
        assert len(statement._with_options) == 2

    def test_list_output_keeps_contract_without_detail_payload(self):
        from app.api.reviews import _to_list_out
        from app.models import ProcessingState

        caller = SimpleNamespace(
            user_upn="alice@taxconsulting.co.za", is_organizer=False,
            access_type="participant", edit_access_status="approved",
            edit_requested_at=None,
        )
        meeting = SimpleNamespace(
            id="meeting-1", recorded_at=None, title="Review", error=None,
            state=ProcessingState.awaiting_review,
            organizer_upn="owner@taxconsulting.co.za",
            attendees_raw=["alice@taxconsulting.co.za"],
            participants=[caller],
        )

        out = _to_list_out(meeting, caller.user_upn)

        assert out.can_edit is True
        assert out.transcript is None
        assert out.extracted_json is None
        assert out.action_items == []
        assert set(out.model_dump()) == set(type(out).model_fields)


class TestHistoricalMeetingsEndpoint:
    async def test_query_filters_attendees_in_database_and_loads_list_columns_only(self):
        from sqlalchemy.dialects import postgresql
        from app.api import reviews

        db = AsyncMock()
        db.scalars.return_value = MagicMock(
            unique=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        assert await reviews.historical_meetings(
            db=db, upn="alice@taxconsulting.co.za"
        ) == []

        statement = db.scalars.await_args.args[0]
        sql = str(statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        ))
        assert "jsonb_array_elements(meetings.attendees_raw)" in sql
        assert "lower(CASE WHEN" in sql
        assert "emailAddress,address" in sql
        assert sql.count("AS TEXT[]") == 2
        assert sql.count("AS TEXT)") == 2
        assert "NOT (EXISTS" in sql
        assert "meetings.transcript" not in sql
        assert "meetings.summary" not in sql
        assert "meetings.extracted_json" not in sql
        assert "meetings.attendees_raw" not in sql.split("FROM meetings", 1)[0]
        assert len(statement._with_options) == 2

    def test_historical_output_keeps_contract_without_detail_payload(self):
        from app.api.reviews import _to_historical_out
        from app.models import ProcessingState

        meeting = SimpleNamespace(
            id="meeting-1",
            recorded_at=None,
            title="Historical review",
            state=ProcessingState.sent,
            organizer_upn="owner@taxconsulting.co.za",
        )

        out = _to_historical_out(meeting)

        assert out.id == "meeting-1"
        assert out.title == "Historical review"
        assert out.transcript is None
        assert out.extracted_json is None
        assert out.calendar_participants == []
        assert out.action_items == []
        assert set(out.model_dump()) == set(type(out).model_fields)


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

    def test_calendar_participants_use_graph_objects_when_extracted_attendees_are_empty(self):
        from app.api.reviews import _to_out
        from app.models import ProcessingState

        meeting = SimpleNamespace(
            id="meeting-1",
            title="test",
            state=ProcessingState.awaiting_review,
            summary=None,
            transcript="Transcript",
            organizer_upn="wei.jiuyang@taxconsulting.co.za",
            extracted_json={"attendees": []},
            error=None,
            recorded_at=None,
            attendees_raw=[
                {"emailAddress": {
                    "name": "Sphesihle  Mhlongo",
                    "address": "sphesihle@taxconsulting.co.za",
                }},
                {"emailAddress": {
                    "name": "Wei Jiuyang",
                    "address": "wei.jiuyang@taxconsulting.co.za",
                }},
            ],
            approved_recipients=[],
            participants=[SimpleNamespace(
                user_upn="shared.viewer@taxconsulting.co.za",
                is_organizer=False,
                access_type="shared",
                edit_access_status="none",
            )],
            action_items=[],
        )

        out = _to_out(meeting)

        assert [participant.model_dump() for participant in out.calendar_participants] == [
            {
                "name": "Sphesihle Mhlongo",
                "email": "sphesihle@taxconsulting.co.za",
                "is_organizer": False,
            },
            {
                "name": "Wei Jiuyang",
                "email": "wei.jiuyang@taxconsulting.co.za",
                "is_organizer": True,
            },
        ]
        assert all(
            participant.email != "shared.viewer@taxconsulting.co.za"
            for participant in out.calendar_participants
        )

    def test_calendar_participants_support_legacy_string_attendees_and_deduplicate(self):
        from app.api.reviews import _to_out
        from app.models import ProcessingState

        meeting = SimpleNamespace(
            id="meeting-2",
            title="Legacy meeting",
            state=ProcessingState.awaiting_review,
            summary=None,
            transcript=None,
            organizer_upn="wei.jiuyang@taxconsulting.co.za",
            extracted_json={"attendees": []},
            error=None,
            recorded_at=None,
            attendees_raw=[
                "sphesihle.mhlongo@taxconsulting.co.za",
                "SPHESIHLE.MHLONGO@taxconsulting.co.za",
            ],
            approved_recipients=[],
            participants=[],
            action_items=[],
        )

        out = _to_out(meeting)

        assert [participant.model_dump() for participant in out.calendar_participants] == [
            {
                "name": "Sphesihle Mhlongo",
                "email": "sphesihle.mhlongo@taxconsulting.co.za",
                "is_organizer": False,
            },
            {
                "name": "Wei Jiuyang",
                "email": "wei.jiuyang@taxconsulting.co.za",
                "is_organizer": True,
            },
        ]


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


class TestAdminMeetingControl:
    @staticmethod
    def _meeting():
        from app.models import ProcessingState

        return MagicMock(
            id="meeting-1", drive_item_id="item-1", title="Private meeting",
            organizer_upn="owner@taxconsulting.co.za", attendees_raw=["owner@taxconsulting.co.za"],
            participants=[], action_items=[SimpleNamespace(
                id="action-1", task="Follow up", owner=None, deadline_text=None,
                deadline_iso=None, confidence="high", source_quote=None, approved=False,
            )],
            state=ProcessingState.awaiting_review, transcript="Transcript", summary="AI notes",
            extracted_json={"speaker_mappings": {}}, error=None, recorded_at=None,
            approved_recipients=[], email_delivery_status=None, email_delivery_fingerprint=None,
            email_delivery_error=None, email_delivery_attempts=0,
        )

    async def test_admin_views_content_without_participant_grant(self):
        from app.api import reviews

        admin = SimpleNamespace(is_admin=True)
        meeting = self._meeting()
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[admin, meeting])

        result = await reviews.get_meeting("meeting-1", db=db, upn="admin@taxconsulting.co.za")

        assert result.transcript == "Transcript" and result.summary == "AI notes"
        assert result.action_items and result.can_edit and result.can_approve
        assert result.is_organizer is False
        db.add.assert_not_called()

    @pytest.mark.parametrize("edit_path", ["transcript", "action_item", "speaker_mappings"])
    async def test_admin_uses_existing_edit_paths(self, monkeypatch, edit_path):
        from app.api import reviews
        from app.schemas import ActionItemEdit, SpeakerMappingIn, TranscriptEdit

        meeting = self._meeting()
        meeting.attendees_raw = ["owner@taxconsulting.co.za"]
        item = SimpleNamespace(id="action-1", meeting_id="meeting-1", task="Old", edited_by=None)
        db = AsyncMock()
        db.get = AsyncMock(return_value=item)
        monkeypatch.setattr(reviews, "_is_admin", AsyncMock(return_value=True))
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        if edit_path == "transcript":
            await reviews.edit_transcript("meeting-1", TranscriptEdit(transcript="Updated"), db=db,
                                          upn="admin@taxconsulting.co.za")
            assert meeting.transcript == "Updated"
        elif edit_path == "action_item":
            await reviews.edit_item("action-1", ActionItemEdit(task="Updated"), db=db,
                                    upn="admin@taxconsulting.co.za")
            assert item.task == "Updated" and item.edited_by == "admin@taxconsulting.co.za"
        else:
            result = await reviews.save_speaker_mappings(
                "meeting-1", SpeakerMappingIn(mappings={"Speaker A": "owner@taxconsulting.co.za"}),
                db=db, upn="admin@taxconsulting.co.za",
            )
            assert result["speaker_mappings"] == {"Speaker A": "owner@taxconsulting.co.za"}
        db.commit.assert_awaited_once()

    async def test_admin_final_approval_uses_existing_email_delivery(self, monkeypatch):
        from app.api import reviews
        from app.models import ProcessingState
        from app.schemas import ApproveMeetingIn

        meeting = self._meeting()
        db = AsyncMock()
        send_mail = AsyncMock()
        monkeypatch.setattr(reviews, "_is_admin", AsyncMock(return_value=True))
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))
        monkeypatch.setattr(reviews.settings, "emails_enabled", True)
        monkeypatch.setattr(reviews, "build_meeting_email", lambda _: ("Subject", "Body"))
        monkeypatch.setattr(reviews.graph, "send_mail", send_mail)

        result = await reviews.approve(
            "meeting-1", db=db, upn="admin@taxconsulting.co.za",
            body=ApproveMeetingIn(recipients=["owner@taxconsulting.co.za"]),
        )

        assert result["state"] == ProcessingState.sent
        assert meeting.approved_by == "admin@taxconsulting.co.za"
        send_mail.assert_awaited_once()
        assert send_mail.await_args.args[1:] == (["owner@taxconsulting.co.za"], "Subject", "Body")


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

    @pytest.mark.parametrize("requested_access", ["view", "edit"])
    async def test_historical_attendee_requests_selected_access(self, requested_access):
        from app.api import reviews
        from app.schemas import MeetingAccessRequestIn

        meeting, _ = self._meeting()
        meeting.participants = []
        db = MagicMock()
        db.scalar = AsyncMock(side_effect=[meeting, None])
        db.commit = AsyncMock()

        result = await reviews.request_historical_access(
            "meeting-1", MeetingAccessRequestIn(access_type=requested_access),
            db=db, upn="guest@taxconsulting.co.za",
        )

        participant = db.add.call_args.args[0]
        assert participant.access_type == f"request_{requested_access}"
        assert participant.edit_access_status == "pending"
        assert result == {
            "ok": True, "status": "pending", "access_type": requested_access
        }
        db.commit.assert_awaited_once()

    @pytest.mark.parametrize(
        ("access_type", "edit_status"),
        [("revoked", "denied"), ("request_view", "denied")],
    )
    async def test_revoked_or_rejected_view_can_be_requested_again(
        self, access_type, edit_status
    ):
        from app.api import reviews
        from app.schemas import MeetingAccessRequestIn

        meeting, participant = self._meeting(
            access_type=access_type, status=edit_status
        )
        meeting.attendees_raw = []
        db = MagicMock()
        db.scalar = AsyncMock(side_effect=[meeting, participant])
        db.commit = AsyncMock()

        result = await reviews.request_historical_access(
            "meeting-1", MeetingAccessRequestIn(access_type="view"),
            db=db, upn="guest@taxconsulting.co.za",
        )

        assert result == {"ok": True, "status": "pending", "access_type": "view"}
        assert participant.access_type == "request_view"
        assert participant.edit_access_status == "pending"
        assert participant.edit_decided_at is None
        assert participant.edit_decided_by is None
        db.commit.assert_awaited_once()

    @pytest.mark.parametrize(
        ("access_type", "edit_status"),
        [("request_view", "pending"), ("historical", "none")],
    )
    async def test_pending_or_approved_view_cannot_be_requested_again(
        self, access_type, edit_status
    ):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import MeetingAccessRequestIn

        meeting, participant = self._meeting(
            access_type=access_type, status=edit_status
        )
        db = MagicMock()
        db.scalar = AsyncMock(side_effect=[meeting, participant])
        db.commit = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await reviews.request_historical_access(
                "meeting-1", MeetingAccessRequestIn(access_type="view"),
                db=db, upn="guest@taxconsulting.co.za",
            )

        assert exc.value.status_code == 409
        db.commit.assert_not_awaited()

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

    @pytest.mark.parametrize("request_type", ["request_view", "request_edit"])
    @pytest.mark.parametrize("approved", [True, False])
    async def test_admin_can_decide_pending_view_and_edit_requests(
        self, monkeypatch, request_type, approved
    ):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import EditAccessDecisionIn

        meeting, participant = self._meeting(access_type=request_type, status="pending")
        admin = MagicMock(upn="admin@taxconsulting.co.za", is_admin=True)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[admin, meeting])
        monkeypatch.setattr(
            reviews, "_authorize",
            AsyncMock(side_effect=HTTPException(403, "Not a participant of this meeting")),
        )

        result = await reviews.decide_edit_access(
            "meeting-1", "guest@taxconsulting.co.za",
            EditAccessDecisionIn(approved=approved), db=db,
            upn="admin@taxconsulting.co.za",
        )

        assert result == {
            "ok": True,
            "status": "approved" if approved else "denied",
            "access_type": "view" if request_type == "request_view" else "edit",
        }
        assert participant.edit_decided_by == "admin@taxconsulting.co.za"
        if approved:
            assert participant.access_type == "historical"
            assert participant.edit_access_status == ("none" if request_type == "request_view" else "approved")
        else:
            assert participant.access_type == request_type
            assert participant.edit_access_status == "denied"

    @pytest.mark.parametrize("decided_status", ["approved", "denied"])
    async def test_admin_cannot_decide_request_twice(self, monkeypatch, decided_status):
        from fastapi import HTTPException
        from app.api import reviews
        from app.schemas import EditAccessDecisionIn

        meeting, _ = self._meeting(access_type="request_edit", status=decided_status)
        admin = MagicMock(upn="admin@taxconsulting.co.za", is_admin=True)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[admin, meeting])
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(side_effect=HTTPException(403)))

        with pytest.raises(HTTPException) as exc:
            await reviews.decide_edit_access(
                "meeting-1", "guest@taxconsulting.co.za",
                EditAccessDecisionIn(approved=True), db=db,
                upn="admin@taxconsulting.co.za",
            )

        assert exc.value.status_code == 409
        db.commit.assert_not_awaited()

    @pytest.mark.parametrize(
        ("request_type", "expected_edit_status"),
        [("request_view", "none"), ("request_edit", "approved")],
    )
    async def test_organizer_grants_requested_access_type(
        self, monkeypatch, request_type, expected_edit_status
    ):
        from app.api import reviews
        from app.schemas import EditAccessDecisionIn

        meeting, participant = self._meeting(access_type=request_type, status="pending")
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        result = await reviews.decide_edit_access(
            "meeting-1", "guest@taxconsulting.co.za",
            EditAccessDecisionIn(approved=True), db=db,
            upn="owner@taxconsulting.co.za",
        )

        assert result == {
            "ok": True,
            "status": "approved",
            "access_type": "view" if request_type == "request_view" else "edit",
        }
        assert participant.access_type == "historical"
        assert participant.edit_access_status == expected_edit_status

    async def test_pending_access_row_does_not_authorize_meeting_detail(self):
        from fastapi import HTTPException
        from app.api import reviews

        meeting, _ = self._meeting(access_type="request_view", status="pending")
        db = AsyncMock()
        db.scalar.return_value = meeting

        with pytest.raises(HTTPException) as exc:
            await reviews._authorize(db, "meeting-1", "guest@taxconsulting.co.za")

        assert exc.value.status_code == 403

    def test_view_access_cannot_edit_but_edit_access_can(self):
        from fastapi import HTTPException
        from app.api import reviews

        view_meeting, _ = self._meeting(access_type="historical", status="none")
        with pytest.raises(HTTPException) as exc:
            reviews._require_editor(view_meeting, "guest@taxconsulting.co.za")
        assert exc.value.status_code == 403

        edit_meeting, _ = self._meeting(access_type="historical", status="approved")
        reviews._require_editor(edit_meeting, "guest@taxconsulting.co.za")

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

    async def test_approved_attendee_can_save_speaker_mappings(self, monkeypatch):
        from app.api import reviews
        from app.schemas import SpeakerMappingIn

        meeting, _ = self._meeting(status="approved")
        meeting.extracted_json = {}
        db = AsyncMock()
        monkeypatch.setattr(reviews, "_authorize", AsyncMock(return_value=meeting))

        mappings = {
            "Speaker A": "guest@taxconsulting.co.za",
            "Speaker B": "owner@taxconsulting.co.za",
        }
        result = await reviews.save_speaker_mappings(
            "meeting-1", SpeakerMappingIn(mappings=mappings), db=db,
            upn="guest@taxconsulting.co.za",
        )

        assert result == {"ok": True, "speaker_mappings": mappings}
        assert meeting.extracted_json["speaker_mappings"] == mappings
        db.commit.assert_awaited_once()

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

    def test_prefers_normal_five_to_ten_second_candidate(self):
        from app.api.reviews import _speaker_sample_window

        meeting = self._meeting()
        meeting.extracted_json["transcript_segments"] = [
            {"speaker": "Speaker B", "start": 0.0, "end": 2.0},
            {"speaker": "Speaker A", "start": 5.0, "end": 11.0},
            {"speaker": "Speaker A", "start": 20.0, "end": 27.0},
            {"speaker": "Speaker B", "start": 35.0, "end": 40.0},
        ]

        assert _speaker_sample_window(meeting, "speaker a") == (20.0, 27.0)

    def test_centres_eight_second_window_inside_long_candidate(self):
        from app.api.reviews import _speaker_sample_window

        assert _speaker_sample_window(self._meeting(), "speaker a") == (16.0, 24.0)

    def test_normal_candidate_does_not_cross_competing_speaker_boundary(self):
        from app.api.reviews import _speaker_sample_window

        meeting = self._meeting()
        meeting.extracted_json["transcript_segments"] = [
            {"speaker": "Speaker B", "start": 3.0, "end": 5.0},
            {"speaker": "Speaker A", "start": 5.0, "end": 11.0},
            {"speaker": "Speaker B", "start": 11.0, "end": 15.0},
        ]

        assert _speaker_sample_window(meeting, "Speaker A") == (5.0, 11.0)

    def test_short_segment_retains_safe_padded_fallback(self):
        from app.api.reviews import _speaker_sample_window

        assert _speaker_sample_window(self._meeting(), "Speaker B") == (30.75, 35.75)

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
