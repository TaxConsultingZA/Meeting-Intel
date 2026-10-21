"""Offline regression coverage for the complete, permission-scoped catalog."""
from datetime import UTC, datetime, timedelta
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
    RecordingJob,
    RecordingProcessingRequest,
    RegisteredUser,
    SyncedCalendarEvent,
)
from app.services import cross_user_recordings as service


@pytest.fixture
def catalog():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = RegisteredUser(upn="attendee@example.test", is_subscribed=True)
        session.add(user)
        session.commit()
        yield SimpleNamespace(
            session=session, user=user,
            db=SimpleNamespace(
                scalars=AsyncMock(side_effect=session.scalars),
                scalar=AsyncMock(side_effect=session.scalar),
                execute=AsyncMock(side_effect=session.execute),
            ),
        )
    engine.dispose()


def event(ctx, event_id, days, **overrides):
    start = datetime.now(UTC) + timedelta(days=days)
    raw = {
        "id": event_id, "iCalUId": f"ical-{event_id}", "subject": "Same title",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(hours=1)).isoformat()},
        "organizer": {"emailAddress": {"address": "host@external.example"}},
        "attendees": [{"emailAddress": {"address": ctx.user.upn}}],
        **overrides,
    }
    ctx.session.add(SyncedCalendarEvent(
        user_upn=ctx.user.upn, event_id=event_id, starts_at=start,
        ends_at=start + timedelta(hours=1), raw=raw,
    ))
    return raw


async def test_all_cache_dates_kinds_and_no_recording_without_discovery(catalog, monkeypatch):
    ctx = catalog
    discover = AsyncMock(side_effect=AssertionError("Page reads must not discover recordings"))
    monkeypatch.setattr(service, "discover", discover)
    wanted = [
        event(ctx, "old-offline", -400, isOnlineMeeting=False),
        event(ctx, "past-boundary", -31), event(ctx, "recent", -1),
        event(ctx, "ongoing", -0.01), event(ctx, "future", 1),
        event(ctx, "future-outside-seven", 8), event(ctx, "far-future", 400),
        event(ctx, "cancelled", -2, isCancelled=True),
        event(ctx, "undated", -2, start=None, end=None),
    ]
    # Verify a catalog read has no implicit first-page limit.
    wanted.extend(event(ctx, f"older-{index}", -100) for index in range(125))
    # A cache row alone cannot expose somebody else's invitation to this user.
    event(ctx, "nonparticipant", -1, attendees=[])
    ctx.session.add(SyncedCalendarEvent(
        user_upn="outsider@example.test", event_id="other-cache", raw=wanted[0],
    ))
    ctx.session.commit()
    rows = await calendar.recent_meetings(db=ctx.db, upn=ctx.user.upn, all_available=True)
    assert {row["event_id"] for row in rows} == {row["id"] for row in wanted}
    by_id = {row["event_id"]: row for row in rows}
    assert by_id["old-offline"]["status"] == "ended"
    assert by_id["ongoing"]["status"] == "in_progress"
    assert by_id["far-future"]["status"] == "upcoming"
    assert all(row["action"] == "no_recording" for row in rows)
    assert await calendar.recent_meetings(db=ctx.db, upn=ctx.user.upn) != rows
    discover.assert_not_awaited()
    assert not ctx.session.dirty and not ctx.session.new and not ctx.session.deleted


@pytest.mark.parametrize("state", list(ProcessingState))
async def test_all_meeting_states_bind_by_identity_and_keep_access_rules(catalog, state):
    ctx = catalog
    raw = event(ctx, "bound", -100)
    meeting = Meeting(
        drive_item_id="offline-bound", title="Stored record", state=state,
        recorded_at=datetime.now(UTC) - timedelta(days=100),
        extracted_json={"calendar_occurrence_key": service.occurrence_key(raw)},
        participants=[MeetingParticipant(user_upn=ctx.user.upn, access_type="participant")],
    )
    ctx.session.add(meeting)
    ctx.session.commit()
    stored = await reviews.all_meetings(db=ctx.db, upn=ctx.user.upn)
    rows = await calendar.recent_meetings(db=ctx.db, upn=ctx.user.upn, all_available=True)
    assert len(stored) == len(rows) == 1
    assert rows[0]["meeting_id"] == stored[0].id == str(meeting.id)
    assert rows[0]["action"] == "view"
    for access in ("request_view", "request_edit", "revoked"):
        meeting.participants[0].access_type = access
        ctx.session.commit()
        assert await reviews.all_meetings(db=ctx.db, upn=ctx.user.upn) == []
        rows = await calendar.recent_meetings(db=ctx.db, upn=ctx.user.upn, all_available=True)
        assert rows[0]["action"] != "view"


async def test_no_title_based_or_ambiguous_catalog_binding(catalog):
    ctx = catalog
    raw = event(ctx, "ambiguous", -1)
    for index in range(2):
        ctx.session.add(Meeting(
            drive_item_id=f"offline-ambiguous-{index}", title=raw["subject"],
            recorded_at=service.parse_graph_datetime(raw["start"]),
            organizer_upn="host@external.example", state=ProcessingState.approved,
            extracted_json={"calendar_occurrence_key": service.occurrence_key(raw)},
            participants=[MeetingParticipant(user_upn=ctx.user.upn, access_type="participant")],
        ))
    same_label = event(ctx, "distinct-id-same-title", -1)
    same_label["start"] = raw["start"]
    same_label["end"] = raw["end"]
    ctx.session.commit()
    rows = await calendar.recent_meetings(db=ctx.db, upn=ctx.user.upn, all_available=True)
    assert len(rows) == 2
    assert all("meeting_id" not in row for row in rows)


async def test_enriched_outlook_id_is_a_stable_binding(catalog):
    ctx = catalog
    raw = event(ctx, "enriched", -100)
    meeting = Meeting(
        drive_item_id="offline-enriched", state=ProcessingState.failed,
        extracted_json={"outlook_event_id": raw["id"]},
        participants=[MeetingParticipant(user_upn=ctx.user.upn, access_type="participant")],
    )
    ctx.session.add(meeting)
    ctx.session.commit()
    rows = await calendar.recent_meetings(db=ctx.db, upn=ctx.user.upn, all_available=True)
    assert rows[0]["meeting_id"] == str(meeting.id)


@pytest.mark.parametrize("access_type", ["shared", "historical"])
async def test_existing_shared_and_historical_grants_are_catalogued(catalog, access_type):
    ctx = catalog
    meeting = Meeting(
        drive_item_id=f"offline-{access_type}", state=ProcessingState.approved,
        participants=[MeetingParticipant(user_upn=ctx.user.upn, access_type=access_type)],
    )
    ctx.session.add(meeting)
    ctx.session.commit()
    rows = await reviews.all_meetings(db=ctx.db, upn=ctx.user.upn)
    assert [row.id for row in rows] == [str(meeting.id)]


@pytest.mark.parametrize("job_status", ["pending", "processing", "failed", "completed"])
async def test_acquired_calendar_with_existing_job_is_visible_without_changing_job(catalog, job_status):
    ctx = catalog
    raw = event(ctx, "job-event", -100)
    job = RecordingJob(
        drive_item_id="offline-item", drive_id="offline-drive", owner_upn=ctx.user.upn,
        source="offline", status=job_status, attempts=2,
    )
    request = RecordingProcessingRequest(
        requester_user_id=ctx.user.id, recording_owner_user_id=ctx.user.id,
        event_id=raw["id"], occurrence_key=service.occurrence_key(raw), event_snapshot=raw,
        drive_id="offline-drive", drive_item_id="offline-item", status="approved",
    )
    ctx.session.add_all([job, request])
    ctx.session.commit()
    before = (job.status, job.attempts, job.updated_at, request.status)
    rows = await calendar.recent_meetings(db=ctx.db, upn=ctx.user.upn, all_available=True)
    assert len(rows) == 1
    assert rows[0]["processing_status"] == job_status
    assert "meeting_id" not in rows[0]
    assert before == (job.status, job.attempts, job.updated_at, request.status)
    assert not ctx.session.dirty and not ctx.session.new
