"""Tests for app/api/reviews.py — domain validation and endpoint behaviour (mocked DB)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


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
        result = await current_user(x_user_upn="alice@taxconsulting.co.za")
        assert result == "alice@taxconsulting.co.za"

    async def test_outside_domain_raises_403(self):
        from fastapi import HTTPException
        from app.api.reviews import current_user
        with pytest.raises(HTTPException) as exc_info:
            await current_user(x_user_upn="alice@otherdomain.com")
        assert exc_info.value.status_code == 403

    def test_missing_header_raises_422(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/reviews/all")
        assert resp.status_code == 422


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
        resp = client.get("/reviews/all", headers={"x-user-upn": "alice@taxconsulting.co.za"})
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
        m.organizer_upn = "organiser@taxconsulting.co.za"
        m.extracted_json = None
        m.error = None
        m.action_items = []
        out = _to_out(m)
        assert out.id == "uuid-1"
        assert out.title == "Budget Meeting"
        assert out.state == ProcessingState.awaiting_review
