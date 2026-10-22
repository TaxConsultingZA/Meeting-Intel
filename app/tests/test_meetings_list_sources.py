"""Stored review visibility is independent of the calendar discovery window."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import calendar, reviews
from app.db import Base
from app.models import (
    Meeting,
    MeetingParticipant,
    ProcessingState,
    RegisteredUser,
    SyncedCalendarEvent,
)
from app.services import cross_user_recordings


@pytest.mark.parametrize("cache", ["missing", "expired"])
async def test_authorised_reviews_survive_missing_or_expired_calendar(cache, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    upn = "attendee@example.test"
    states = AsyncMock(return_value={})
    monkeypatch.setattr(cross_user_recordings, "recent_states", states)
    try:
        with Session(engine) as session:
            session.add(RegisteredUser(upn=upn, is_subscribed=True))
            stored = []
            for index, date in enumerate(("2026-09-01", "2026-09-02", "2026-08-21")):
                meeting = Meeting(
                    drive_item_id=f"offline-recording-{index}", title=f"Offline review {index}",
                    organizer_upn="host@external.example",
                    recorded_at=datetime.fromisoformat(date).replace(tzinfo=UTC),
                    state=ProcessingState.awaiting_review, attendees_raw=[upn],
                    participants=[MeetingParticipant(user_upn=upn, access_type="participant")]
                    + [MeetingParticipant(user_upn=f"{access}@example.test", access_type=access)
                       for access in ("request_view", "request_edit", "revoked")],
                )
                session.add(meeting)
                stored.append(meeting)
            # Attendee metadata alone must never grant visibility.
            session.add(Meeting(
                drive_item_id="offline-denied", attendees_raw=[upn],
                participants=[MeetingParticipant(user_upn=upn, access_type="revoked")],
            ))
            if cache == "expired":
                session.add(SyncedCalendarEvent(
                    user_upn=upn, event_id="offline-expired",
                    ends_at=datetime(2000, 1, 1, tzinfo=UTC), raw={},
                ))
            session.commit()
            db = SimpleNamespace(
                scalars=AsyncMock(side_effect=session.scalars),
                scalar=AsyncMock(side_effect=session.scalar),
            )
            result = await reviews.all_meetings(db=db, upn=upn)
            assert {item.id for item in result} == {str(meeting.id) for meeting in stored}
            assert all(not item.is_organizer and not item.can_edit for item in result)
            assert await calendar.recent_meetings(db=db, upn=upn) == []
            states.assert_awaited_once()
            assert states.await_args.args[2] == []
            for denied in ("outsider", "request_view", "request_edit", "revoked"):
                assert await reviews.all_meetings(db=db, upn=f"{denied}@example.test") == []
    finally:
        engine.dispose()
