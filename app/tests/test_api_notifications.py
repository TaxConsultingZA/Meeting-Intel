"""Tests for app/api/notifications.py — notification shape and filtering."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models import ProcessingState


def _mock_meeting(state: ProcessingState, title: str = "Test Meeting") -> MagicMock:
    from datetime import datetime, timezone
    m = MagicMock()
    m.id = "meeting-uuid"
    m.title = title
    m.state = state
    m.created_at = datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc)
    return m


class TestNotificationsEndpoint:
    def _make_db(self, meetings):
        """Build an AsyncMock db whose scalars() → unique() → all() chain returns meetings."""
        mock_db = AsyncMock()
        # db.scalars() is awaited, returning an object with .unique().all()
        scalars_result = MagicMock()
        scalars_result.unique.return_value.all.return_value = meetings
        mock_db.scalars = AsyncMock(return_value=scalars_result)
        return mock_db

    async def test_awaiting_review_produces_ready_for_review_notification(self):
        from app.api.notifications import get_notifications
        meeting = _mock_meeting(ProcessingState.awaiting_review, "Compliance Review")
        result = await get_notifications(db=self._make_db([meeting]), upn="user@taxconsulting.co.za")
        assert len(result) == 1
        assert result[0]["type"] == "ready_for_review"
        assert result[0]["title"] == "Compliance Review"
        assert result[0]["link"] is not None
        assert "meeting-uuid" in result[0]["link"]

    async def test_sent_state_produces_notes_sent_notification(self):
        from app.api.notifications import get_notifications
        meeting = _mock_meeting(ProcessingState.sent)
        result = await get_notifications(db=self._make_db([meeting]), upn="user@taxconsulting.co.za")
        assert result[0]["type"] == "notes_sent"

    async def test_failed_state_produces_failed_notification(self):
        from app.api.notifications import get_notifications
        meeting = _mock_meeting(ProcessingState.failed)
        result = await get_notifications(db=self._make_db([meeting]), upn="user@taxconsulting.co.za")
        assert result[0]["type"] == "failed"
        assert result[0]["link"] is None

    async def test_queued_state_excluded(self):
        from app.api.notifications import get_notifications
        meeting = _mock_meeting(ProcessingState.queued)
        result = await get_notifications(db=self._make_db([meeting]), upn="user@taxconsulting.co.za")
        assert result == []

    async def test_untitled_meeting_uses_fallback(self):
        from app.api.notifications import get_notifications
        meeting = _mock_meeting(ProcessingState.sent, title=None)
        result = await get_notifications(db=self._make_db([meeting]), upn="user@taxconsulting.co.za")
        assert result[0]["title"] == "Untitled Meeting"
