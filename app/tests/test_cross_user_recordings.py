"""Offline T5 service/route tests using real SQLAlchemy rows in memory.

SQLite is only a test adapter; PostgreSQL constraints are separately compiled.
No Graph, transcription, mail, or staging database connections are permitted.
"""
from copy import deepcopy
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex
from sqlalchemy.dialects import postgresql

from app.models import Base, RegisteredUser, RecordingJob, Meeting, MeetingParticipant, RecordingProcessingRequest, ProcessedItem, ProcessingState, SyncedCalendarEvent
from app.services import cross_user_recordings as service
from app.api import calendar, recordings, recording_processing_requests
from app.api.recording_processing_requests import EventReference, public_request


class OfflineDB:
    def __init__(self, session):
        self.session = session
    def add(self, value):
        self.session.add(value)
    async def scalar(self, query):
        return self.session.scalar(query)
    async def scalars(self, query):
        return self.session.scalars(query)
    async def execute(self, query):
        return self.session.execute(query)
    async def get(self, model, key):
        return self.session.get(model, key)
    async def flush(self):
        self.session.flush()
    async def commit(self):
        self.session.commit()
    async def rollback(self):
        self.session.rollback()


@pytest.fixture
def ctx(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    # Keep the production partial-index predicate for SQLite's test schema.
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            predicate = index.dialect_options["postgresql"].get("where")
            if predicate is not None:
                index.dialect_options["sqlite"]["where"] = predicate
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    users = [RegisteredUser(upn=f"{name}@taxconsulting.co.za", is_subscribed=True)
             for name in ("requester", "owner", "organizer", "outsider")]
    admin = RegisteredUser(upn="admin@taxconsulting.co.za", is_admin=True, is_subscribed=False)
    users.append(admin)
    session.add_all(users)
    session.commit()
    requester, owner, organizer, outsider, admin = users
    now = datetime.now(timezone.utc)
    event = {
        "id": "requester-event", "iCalUId": "same-occurrence", "subject": "Project Review",
        "start": {"dateTime": (now-timedelta(hours=2)).isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now-timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
        "organizer": {"emailAddress": {"address": organizer.upn}},
        "attendees": [{"emailAddress": {"address": u.upn}} for u in (requester, owner)],
    }
    item = {"id": "item", "name": "Project Review-20260904_120000-Meeting Recording.mp4",
            "createdDateTime": (now-timedelta(minutes=90)).isoformat()}
    monkeypatch.setattr(service.graph, "get_calendar_event", AsyncMock(side_effect=lambda *args: deepcopy(event)))
    monkeypatch.setattr(service.graph, "get_calendar_window", AsyncMock(side_effect=lambda *args: [deepcopy(event)]))
    monkeypatch.setattr(service.graph, "get_user_drive_id", AsyncMock(side_effect=lambda upn: f"drive:{upn}"))
    monkeypatch.setattr(service.graph, "get_drive_item", AsyncMock(side_effect=lambda *args: deepcopy(item)))
    scan = AsyncMock(side_effect=lambda drive, **kw: [deepcopy(item)] if drive == f"drive:{owner.upn}" else [])
    monkeypatch.setattr(service.graph, "list_recordings_folder", scan)
    yield SimpleNamespace(db=OfflineDB(session), session=session, requester=requester, owner=owner,
                          organizer=organizer, outsider=outsider, admin=admin, event=event, item=item, scan=scan)
    session.close()
    engine.dispose()


async def request(ctx):
    return await service.create_request(ctx.db, ctx.requester.upn, ctx.event["id"])


async def test_recent_ended_window_and_upcoming_uses_future_persisted_events(ctx, monkeypatch):
    now = datetime.now(timezone.utc)
    events = []
    for name, offset in [("recent", -1), ("recent_21_days", -24*21), ("old", -24*31), ("ongoing", 1), ("future", 24)]:
        event = deepcopy(ctx.event)
        event["id"] = name
        event["isOnlineMeeting"] = True
        event["end"]["dateTime"] = (now+timedelta(hours=offset)).isoformat()
        event["start"]["dateTime"] = (now+timedelta(hours=offset-2)).isoformat()
        events.append(event)
    monkeypatch.setattr(service.graph, "get_upcoming_calendar_events", AsyncMock(return_value=events))
    monkeypatch.setattr(service, "recent_state", AsyncMock(return_value={"action": "no_recording"}))
    for event in events:
        ctx.session.add(SyncedCalendarEvent(
            user_upn=ctx.requester.upn, event_id=event["id"], raw=event,
            starts_at=service.parse_graph_datetime(event["start"]),
            ends_at=service.parse_graph_datetime(event["end"]),
        ))
    ctx.session.commit()
    recent = await calendar.recent_meetings(ctx.db, ctx.requester.upn)
    assert [r["event_id"] for r in recent] == ["recent", "recent_21_days"]
    assert recent[0]["status"] == "ended"
    upcoming = await calendar.upcoming_meetings(7, ctx.db, ctx.requester.upn)
    assert [row["event_id"] for row in upcoming] == ["future"]
    service.graph.get_upcoming_calendar_events.assert_not_awaited()
    assert calendar._event_status(events[3]["start"]["dateTime"], events[3]["end"]["dateTime"]) == "in_progress"


async def test_upcoming_does_not_fall_back_to_graph_when_sync_cache_is_empty(ctx, monkeypatch):
    event = deepcopy(ctx.event)
    event["isOnlineMeeting"] = True
    event["start"]["dateTime"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    event["end"]["dateTime"] = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    get_events = AsyncMock(return_value=[event])
    monkeypatch.setattr(service.graph, "get_upcoming_calendar_events", get_events)

    upcoming = await calendar.upcoming_meetings(7, ctx.db, ctx.requester.upn)

    assert upcoming == []
    get_events.assert_not_awaited()


async def test_recent_request_uses_durable_state_without_graph_scans(ctx, monkeypatch):
    events = [deepcopy(ctx.event), deepcopy(ctx.event)]
    events[0]["id"], events[1]["id"] = "newer", "older"
    events[1]["start"]["dateTime"] = (
        service.parse_graph_datetime(events[1]["start"]) - timedelta(days=1)
    ).isoformat()
    events[1]["end"]["dateTime"] = (
        service.parse_graph_datetime(events[1]["end"]) - timedelta(days=1)
    ).isoformat()
    for event in events:
        ctx.session.add(SyncedCalendarEvent(
            user_upn=ctx.requester.upn, event_id=event["id"], raw=event,
            starts_at=service.parse_graph_datetime(event["start"]),
            ends_at=service.parse_graph_datetime(event["end"]),
        ))
    ctx.session.commit()

    result = await calendar.recent_meetings(ctx.db, ctx.requester.upn)

    assert len(result) == 2
    service.graph.get_calendar_event.assert_not_awaited()
    service.graph.get_calendar_window.assert_not_awaited()
    service.graph.get_user_drive_id.assert_not_awaited()
    ctx.scan.assert_not_awaited()


@pytest.mark.parametrize(
    ("access_type", "edit_status", "is_organizer", "is_admin", "expected"),
    [
        ("revoked", "denied", False, False, ("request_access", True, True, None)),
        ("request_view", "denied", False, False, ("request_access", True, True, None)),
        ("request_view", "pending", False, False, ("request_pending", False, False, "view")),
        ("historical", "none", False, False, ("view", False, True, None)),
        ("historical", "pending", False, False, ("view", False, False, "edit")),
        ("revoked", "approved", False, False, ("request_access", True, False, None)),
        ("revoked", "denied", True, False, ("request_access", False, False, None)),
        ("revoked", "denied", False, True, ("request_access", False, False, None)),
    ],
)
async def test_recent_card_uses_effective_meeting_access(
    ctx, access_type, edit_status, is_organizer, is_admin, expected
):
    meeting = Meeting(
        drive_item_id="effective-access-item",
        organizer_upn=ctx.organizer.upn,
        title=ctx.event["subject"],
        recorded_at=service.parse_graph_datetime(ctx.event["start"]),
        state=ProcessingState.awaiting_review,
        attendees_raw=ctx.event["attendees"],
        extracted_json={"calendar_occurrence_key": service.occurrence_key(ctx.event)},
    )
    participant = MeetingParticipant(
        meeting=meeting,
        user_upn=ctx.requester.upn,
        is_organizer=is_organizer,
        access_type=access_type,
        edit_access_status=edit_status,
    )
    ctx.requester.is_admin = is_admin
    ctx.session.add_all([meeting, participant])
    ctx.session.commit()

    state = (await service.recent_states(ctx.db, ctx.requester, [ctx.event]))[
        service.occurrence_key(ctx.event)
    ]

    assert (
        state["action"],
        state["can_request_view_access"],
        state["can_request_edit_access"],
        state["pending_access_type"],
    ) == expected
    assert state["meeting_id"] == str(meeting.id)


async def test_available_recordings_uses_reconciled_rows_without_graph(ctx):
    ctx.requester.graph_drive_id = "drive:requester"
    meeting = Meeting(
        drive_item_id="persisted-item",
        title="Persisted recording.mp4",
        recorded_at=datetime.now(timezone.utc),
        state=ProcessingState.awaiting_review,
    )
    ctx.session.add_all([
        ProcessedItem(
            drive_item_id="persisted-item", drive_id="drive:requester",
            source="reconcile",
        ),
        RecordingJob(
            drive_item_id="persisted-item", drive_id="drive:requester",
            owner_upn=ctx.requester.upn, source="reconcile", status="completed",
        ),
        meeting,
    ])
    ctx.session.commit()

    result = await recordings.available_recordings(ctx.db, ctx.requester.upn)

    assert result == [{
        "drive_item_id": "persisted-item",
        "drive_id": "drive:requester",
        "name": "Persisted recording.mp4",
        "original_filename": None,
        "calendar_matched": False,
        "size": None,
        "created_at": meeting.recorded_at.isoformat(),
        "already_imported": True,
        "meeting_id": str(meeting.id),
        "meeting_state": ProcessingState.awaiting_review,
        "meeting_error": None,
    }]
    service.graph.get_user_drive_id.assert_not_awaited()
    ctx.scan.assert_not_awaited()


async def test_available_recordings_falls_back_to_persisted_filename(ctx):
    ctx.requester.graph_drive_id = "drive:requester"
    ctx.session.add(ProcessedItem(
        drive_item_id="01LIX265PTELCPYQNCLVGIOIWYN7ZXLGRR",
        drive_id="drive:requester", filename="test03.mp4", source="reconcile",
    ))
    ctx.session.commit()

    result = await recordings.available_recordings(ctx.db, ctx.requester.upn)

    assert len(result) == 1
    assert result[0]["name"] == "test03.mp4"
    assert result[0]["meeting_id"] is None
    assert result[0]["already_imported"] is False


async def test_original_filename_is_independent_of_legacy_calendar_title_without_writes(ctx, monkeypatch):
    ctx.requester.graph_drive_id = "drive:requester"
    ledger = ProcessedItem(drive_item_id="legacy-test", drive_id="drive:requester", source="manual")
    meeting = Meeting(drive_item_id="legacy-test", title="Unrelated calendar title",
        state=ProcessingState.awaiting_review, transcript="Existing transcript", summary="Existing notes",
        extracted_json={"outlook_event_id": "legacy-event"})
    ctx.session.add_all([ledger, meeting]); ctx.session.commit()
    metadata = AsyncMock(return_value={"id": "legacy-test", "name": "Test-20260901_164158-会议记录.mp4"})
    monkeypatch.setattr(recordings.graph, "get_drive_item", metadata)
    rows = await recordings.available_recordings(ctx.db, ctx.requester.upn, resolve_filenames=True)
    assert rows[0]["original_filename"] == "Test-20260901_164158-会议记录.mp4"
    assert rows[0]["name"] == "Unrelated calendar title"
    assert rows[0]["calendar_matched"] is True
    assert rows[0]["meeting_id"] == str(meeting.id)
    assert ledger.filename is None
    assert (meeting.transcript, meeting.summary, meeting.extracted_json) == (
        "Existing transcript", "Existing notes", {"outlook_event_id": "legacy-event"})
    assert not ctx.session.dirty
    metadata.assert_awaited_once_with("drive:requester", "legacy-test")
    assert await recordings.available_recordings(ctx.db, ctx.outsider.upn, resolve_filenames=True) == []
    assert metadata.await_count == 1


@pytest.mark.parametrize("metadata", [
    {"id": "different", "name": "wrong.mp4"},
    {"id": "legacy", "name": "wrong.mp4", "parentReference": {"driveId": "other-drive"}},
    {"id": "legacy", "name": "wrong.mp4", "remoteItem": {"id": "shared"}},
    None,
])
async def test_optional_filename_failure_does_not_hide_saved_recordings(ctx, monkeypatch, metadata):
    ctx.requester.graph_drive_id = "drive:requester"
    ctx.session.add(ProcessedItem(drive_item_id="legacy", drive_id="drive:requester", source="manual"))
    ctx.session.commit()
    read = AsyncMock(return_value=metadata) if metadata else AsyncMock(side_effect=RuntimeError("unavailable"))
    monkeypatch.setattr(recordings.graph, "get_drive_item", read)
    rows = await recordings.available_recordings(ctx.db, ctx.requester.upn, resolve_filenames=True)
    assert len(rows) == 1 and rows[0]["original_filename"] is None
    assert rows[0]["name"] == "Unknown"


async def test_discover_scans_independent_non_requester_owners_concurrently(ctx, monkeypatch):
    active = 0
    maximum = 0

    async def scan(drive, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return []

    monkeypatch.setattr(service.graph, "list_recordings_folder", AsyncMock(side_effect=scan))
    with pytest.raises(HTTPException) as error:
        await service.discover(ctx.db, ctx.requester, ctx.event, recording_cache={})

    assert error.value.status_code == 404
    assert maximum == 2


async def test_nonparticipant_forbidden(ctx):
    with pytest.raises(HTTPException) as error:
        await service.create_request(ctx.db, ctx.outsider.upn, ctx.event["id"])
    assert error.value.status_code == 403
    ctx.scan.assert_not_awaited()


async def test_external_organiser_event_persists_and_is_visible_to_authorised_attendee(ctx, monkeypatch):
    from app.workers.sync_microsoft import store_calendar_events
    external = "host@external.example"
    ctx.event["organizer"] = {"emailAddress": {"address": external}}
    monkeypatch.setattr(service, "recent_states", AsyncMock(return_value={
        service.occurrence_key(ctx.event): {"action": "no_recording"}}))
    assert await store_calendar_events(ctx.db, ctx.requester.upn, [ctx.event]) == (1, 0)
    rows = await calendar.recent_meetings(ctx.db, ctx.requester.upn)
    assert len(rows) == 1
    assert rows[0]["organizer_email"] == external
    assert rows[0]["action"] == "no_recording"
    assert await calendar.recent_meetings(ctx.db, ctx.outsider.upn) == []
    with pytest.raises(HTTPException) as error:
        service.validate_participant(ctx.event, ctx.outsider.upn)
    assert error.value.status_code == 403


async def test_unnamed_recording_rediscovery_repairs_available_name_without_processing(ctx):
    from app.services.ledger import claim_item
    ctx.requester.graph_drive_id = "drive:requester"
    ctx.session.add(ProcessedItem(drive_item_id="unnamed", drive_id="drive:requester",
        filename=None, source="webhook"))
    ctx.session.commit()
    rows = await recordings.available_recordings(ctx.db, ctx.requester.upn)
    assert rows[0]["name"] == "Unknown"
    assert not await claim_item(ctx.db, "unnamed", "drive:requester", None,
        "reconcile", filename="Review.mp4")
    rows = await recordings.available_recordings(ctx.db, ctx.requester.upn)
    assert rows[0]["name"] == "Review.mp4"
    assert rows[0]["meeting_id"] is None
    assert not rows[0]["already_imported"]
    assert list(await ctx.db.scalars(select(RecordingJob))) == []
    service.graph.get_drive_item.assert_not_awaited()
    ctx.scan.assert_not_awaited()


@pytest.mark.parametrize("status", ["pending", "completed"])
@pytest.mark.parametrize("has_meeting", [False, True])
async def test_recording_label_recovery_preserves_existing_job_and_unmatched_state(ctx, status, has_meeting):
    from app.services.ledger import claim_item
    drive = "drive:requester"
    ctx.requester.graph_drive_id = drive
    meeting = Meeting(drive_item_id="legacy-unknown", title="Unknown",
        organizer_upn="host@external.example", state=ProcessingState.awaiting_review)
    ledger = ProcessedItem(drive_item_id="legacy-unknown", drive_id=drive,
        filename=None, source="webhook")
    job = RecordingJob(drive_item_id="legacy-unknown", drive_id=drive,
        owner_upn=ctx.requester.upn, source="webhook", status=status, attempts=1)
    ctx.session.add_all([ledger, job] + ([meeting] if has_meeting else []))
    ctx.session.commit()
    original_job = (job.id, job.status, job.attempts, job.owner_upn, job.source)
    assert not await claim_item(ctx.db, ledger.drive_item_id, drive, None,
        "reconcile", filename="Verified recording.mp4")
    row = (await recordings.available_recordings(ctx.db, ctx.requester.upn))[0]
    assert row["name"] == "Verified recording.mp4"
    assert row["calendar_matched"] is False
    assert row["already_imported"] is True
    assert (job.id, job.status, job.attempts, job.owner_upn, job.source) == original_job
    assert len(list(await ctx.db.scalars(select(RecordingJob)))) == 1
    assert meeting.title == "Unknown"  # Display fallback never rewrites meeting data.
    assert await recordings.available_recordings(ctx.db, ctx.outsider.upn) == []
    ctx.scan.assert_not_awaited()


async def test_recording_label_fallback_never_invents_or_overrides_verified_calendar_titles(ctx):
    drive = "drive:requester"
    ctx.requester.graph_drive_id = drive
    ctx.session.add_all([
        ProcessedItem(drive_item_id="no-metadata", drive_id=drive, source="webhook"),
        ProcessedItem(drive_item_id="verified-title", drive_id=drive,
            filename="Original filename.mp4", source="reconcile"),
        Meeting(drive_item_id="verified-title", title="Unknown",
            extracted_json={"outlook_event_id": "verified-event"}, state=ProcessingState.awaiting_review),
    ])
    ctx.session.commit()
    rows = {row["drive_item_id"]: row for row in await recordings.available_recordings(ctx.db, ctx.requester.upn)}
    assert rows["no-metadata"]["name"] == "Unknown"
    assert rows["no-metadata"]["calendar_matched"] is False
    assert rows["verified-title"]["name"] == "Unknown"
    assert rows["verified-title"]["calendar_matched"] is True


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_external_calendar_binding_is_reported_without_forcing_ambiguous_recordings(ctx, monkeypatch, ambiguous):
    from app.api.reviews import all_meetings
    from app.services import recording_enrichment
    drive = "drive:requester"
    ctx.requester.graph_drive_id = drive
    event = deepcopy(ctx.event)
    event["organizer"] = {"emailAddress": {"address": "host@external.example"}}
    candidates = [event]
    if ambiguous:
        candidates.append({**event, "id": "other", "iCalUId": "other-occurrence"})
    monkeypatch.setattr(recording_enrichment, "events_between", AsyncMock(
        side_effect=[RuntimeError("external mailbox inaccessible"), candidates]))
    meeting = Meeting(drive_item_id=ctx.item["id"], title=ctx.item["name"],
        organizer_upn="host@external.example", state=ProcessingState.awaiting_review)
    job = RecordingJob(drive_item_id=ctx.item["id"], drive_id=drive,
        owner_upn=ctx.requester.upn, source="manual", status="completed", attempts=1)
    ctx.session.add_all([meeting, job, ProcessedItem(drive_item_id=ctx.item["id"],
        drive_id=drive, filename=ctx.item["name"], source="reconcile")])
    ctx.session.flush()
    ctx.session.add(MeetingParticipant(meeting_id=meeting.id, user_upn=ctx.requester.upn,
        is_organizer=False, access_type="participant"))
    ctx.session.commit()
    await recording_enrichment.enrich_recording_from_outlook(
        meeting, drive, ctx.item["id"], candidate_upns=[ctx.requester.upn])
    row = (await recordings.available_recordings(ctx.db, ctx.requester.upn))[0]
    assert row["calendar_matched"] is (not ambiguous)
    assert row["already_imported"] is True
    assert job.status == "completed" and job.attempts == 1
    if ambiguous:
        assert not (meeting.extracted_json or {}).get("outlook_event_id")
        assert row["name"] == ctx.item["name"]
    else:
        assert meeting.extracted_json["outlook_event_id"] == event["id"]
        assert row["name"] == "Project Review"
    assert not (await all_meetings(ctx.db, ctx.requester.upn))[0].is_organizer
    assert await all_meetings(ctx.db, ctx.outsider.upn) == []


@pytest.mark.parametrize("access_type,visible", [
    ("participant", True), ("request_view", False), ("request_edit", False), ("revoked", False)])
async def test_external_organiser_recording_preserves_meeting_access_rules(ctx, access_type, visible):
    from app.api.reviews import all_meetings
    meeting = Meeting(drive_item_id="external-item", title="Review",
        organizer_upn="host@external.example", state=ProcessingState.awaiting_review)
    ctx.session.add(meeting)
    ctx.session.flush()
    ctx.session.add(MeetingParticipant(meeting_id=meeting.id, user_upn=ctx.requester.upn,
        is_organizer=False, access_type=access_type))
    ctx.session.commit()
    rows = await all_meetings(ctx.db, ctx.requester.upn)
    assert bool(rows) is visible
    if visible:
        assert rows[0].organizer_upn == "host@external.example"
        assert not rows[0].is_organizer
        assert not rows[0].can_edit
    assert await all_meetings(ctx.db, ctx.outsider.upn) == []


async def test_unsubscribed_owner_not_scanned(ctx):
    ctx.owner.is_subscribed = False
    await ctx.db.commit()
    with pytest.raises(HTTPException) as error:
        await request(ctx)
    assert error.value.status_code == 404
    assert all(call.args[0] != f"drive:{ctx.owner.upn}" for call in ctx.scan.await_args_list)


async def test_reliable_request_pending_and_duplicate_blocked(ctx):
    result = await request(ctx)
    assert result.status == "pending"
    assert result.recording_owner_user_id == ctx.owner.id
    assert result.drive_id == f"drive:{ctx.owner.upn}"
    assert result.drive_item_id == "item"
    out = public_request(result, ctx.requester.id)
    assert "drive_id" not in out and "drive_item_id" not in out
    with pytest.raises(HTTPException) as error:
        await request(ctx)
    assert error.value.status_code == 409
    assert (await service.recent_state(ctx.db, ctx.requester, ctx.event))["action"] == "request_pending"


@pytest.mark.parametrize("kind", ["ambiguous", "wrong_title", "wrong_time", "wrong_occurrence", "unrelated_owner"])
async def test_unreliable_candidates_rejected(ctx, monkeypatch, kind):
    if kind == "ambiguous":
        ctx.scan.side_effect = lambda drive, **kw: [ctx.item, {**ctx.item, "id": "second"}] if "owner@" in drive else []
    elif kind == "wrong_title":
        ctx.item["name"] = "Other subject.mp4"
    elif kind == "wrong_time":
        ctx.item["createdDateTime"] = (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    elif kind == "wrong_occurrence":
        monkeypatch.setattr(service.graph, "get_calendar_window", AsyncMock(return_value=[{**ctx.event, "iCalUId": "different"}]))
    else:
        ctx.event["attendees"] = ctx.event["attendees"][:1]
    with pytest.raises(HTTPException) as error:
        await request(ctx)
    assert error.value.status_code in (404, 409)
    assert not list(await ctx.db.scalars(select(RecordingProcessingRequest)))


async def test_discovery_error_is_unavailable(ctx):
    ctx.scan.side_effect = RuntimeError("Graph forbidden")
    assert (await service.recent_state(ctx.db, ctx.requester, ctx.event))["action"] == "unavailable"


async def test_approve_atomic_job_and_calendar_access_duplicate_idempotent(ctx):
    result = await request(ctx)
    for other in (ctx.requester, ctx.organizer, ctx.outsider):
        with pytest.raises(HTTPException) as error:
            await service.decide_request(ctx.db, other.upn, result.id, True)
        assert error.value.status_code == 403
    approved = await service.decide_request(ctx.db, ctx.owner.upn, result.id, True)
    job = await ctx.db.get(RecordingJob, approved.job_id)
    assert (job.owner_upn, job.drive_id, job.drive_item_id) == (ctx.owner.upn, f"drive:{ctx.owner.upn}", "item")
    meeting = await ctx.db.get(Meeting, approved.meeting_id)
    assert meeting.organizer_upn == ctx.organizer.upn
    assert set(service.event_people({"attendees": meeting.attendees_raw})[0]) == {ctx.owner.upn, ctx.requester.upn, ctx.organizer.upn}
    participants = list(await ctx.db.scalars(select(MeetingParticipant)))
    assert {p.user_upn for p in participants} == {ctx.owner.upn, ctx.requester.upn, ctx.organizer.upn}
    assert {p.user_upn for p in participants if p.is_organizer} == {ctx.organizer.upn}
    assert all(p.edit_access_status == "none" for p in participants)
    await service.decide_request(ctx.db, ctx.owner.upn, result.id, True)
    assert len(list(await ctx.db.scalars(select(RecordingJob)))) == 1
    state = await service.recent_state(ctx.db, ctx.requester, ctx.event)
    assert state["action"] == "processing" and state["processing_status"] == "pending"


async def test_admin_approves_pending_request_once_through_owner_workflow(ctx):
    result = await request(ctx)

    approved = await service.decide_request(ctx.db, ctx.admin.upn, result.id, True)

    assert approved.status == "approved"
    assert approved.decided_by == ctx.admin.id
    job = await ctx.db.get(RecordingJob, approved.job_id)
    assert (job.owner_upn, job.drive_id, job.drive_item_id) == (
        ctx.owner.upn, f"drive:{ctx.owner.upn}", "item",
    )
    with pytest.raises(HTTPException) as error:
        await service.decide_request(ctx.db, ctx.admin.upn, result.id, True)
    assert error.value.status_code == 409
    assert len(list(await ctx.db.scalars(select(RecordingJob)))) == 1


async def test_admin_rejects_pending_request_once_without_job_or_access(ctx):
    result = await request(ctx)

    rejected = await service.decide_request(ctx.db, ctx.admin.upn, result.id, False)

    assert rejected.status == "denied"
    assert rejected.decided_by == ctx.admin.id
    assert rejected.decided_at is not None
    assert rejected.job_id is None and rejected.meeting_id is None
    assert not list(await ctx.db.scalars(select(RecordingJob)))
    assert not list(await ctx.db.scalars(select(MeetingParticipant)))
    with pytest.raises(HTTPException) as error:
        await service.decide_request(ctx.db, ctx.admin.upn, result.id, False)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await service.decide_request(ctx.db, ctx.admin.upn, result.id, True)
    assert error.value.status_code == 409


async def test_admin_cannot_approve_when_previous_transcription_exists(ctx):
    result = await request(ctx)
    meeting = Meeting(drive_item_id="item", organizer_upn=ctx.organizer.upn,
                      title=ctx.event["subject"], state=ProcessingState.awaiting_review,
                      transcript="Existing transcription")
    ctx.db.add(meeting)
    await ctx.db.commit()

    with pytest.raises(HTTPException) as error:
        await service.decide_request(ctx.db, ctx.admin.upn, result.id, True)

    assert error.value.status_code == 409
    assert result.status == "pending"
    assert not list(await ctx.db.scalars(select(RecordingJob)))


async def test_admin_approval_revalidates_participant_eligibility(ctx):
    result = await request(ctx)
    ctx.event["attendees"] = ctx.event["attendees"][1:]

    with pytest.raises(HTTPException) as error:
        await service.decide_request(ctx.db, ctx.admin.upn, result.id, True)

    assert error.value.status_code == 403
    assert result.status == "pending"


async def test_admin_approval_preserves_duplicate_active_job_safeguard(ctx):
    result = await request(ctx)
    ctx.db.add(ProcessedItem(drive_item_id="item", drive_id=result.drive_id, source="reconcile"))
    ctx.db.add(RecordingJob(drive_item_id="item", drive_id=result.drive_id,
                            owner_upn=ctx.owner.upn, source="reconcile"))
    await ctx.db.commit()

    await service.decide_request(ctx.db, ctx.admin.upn, result.id, True)

    assert len(list(await ctx.db.scalars(select(RecordingJob)))) == 1


async def test_owner_deny_does_not_enqueue(ctx):
    result = await request(ctx)
    assert (await service.decide_request(ctx.db, ctx.owner.upn, result.id, False)).status == "denied"
    assert not list(await ctx.db.scalars(select(RecordingJob)))


@pytest.mark.parametrize("change", ["owner_optout", "requester_removed", "item_changed", "drive_changed"])
async def test_approval_revalidates(ctx, monkeypatch, change):
    result = await request(ctx)
    if change == "owner_optout":
        ctx.owner.is_subscribed = False
    elif change == "requester_removed":
        ctx.event["attendees"] = ctx.event["attendees"][1:]
    elif change == "item_changed":
        ctx.item["id"] = "changed"
    else:
        monkeypatch.setattr(service.graph, "get_user_drive_id", AsyncMock(return_value="different-drive"))
    with pytest.raises(HTTPException):
        await service.decide_request(ctx.db, ctx.owner.upn, result.id, True)
    assert result.status == "pending"
    assert not list(await ctx.db.scalars(select(RecordingJob)))


async def test_processed_result_view_no_request_or_retranscription(ctx):
    result = await request(ctx)
    await service.decide_request(ctx.db, ctx.owner.upn, result.id, True)
    meeting = await ctx.db.get(Meeting, result.meeting_id)
    meeting.state = "awaiting_review"
    meeting.transcript = "Existing transcript"
    await ctx.db.commit()
    assert (await service.recent_state(ctx.db, ctx.requester, ctx.event))["action"] == "view"
    with pytest.raises(HTTPException) as error:
        await request(ctx)
    assert error.value.status_code == 409
    assert len(list(await ctx.db.scalars(select(RecordingJob)))) == 1


async def test_active_job_reused_on_approval(ctx):
    result = await request(ctx)
    ctx.db.add(ProcessedItem(drive_item_id="item", drive_id=result.drive_id, source="reconcile"))
    ctx.db.add(RecordingJob(drive_item_id="item", drive_id=result.drive_id, owner_upn=ctx.owner.upn, source="reconcile"))
    await ctx.db.commit()
    await service.decide_request(ctx.db, ctx.owner.upn, result.id, True)
    assert len(list(await ctx.db.scalars(select(RecordingJob)))) == 1


async def test_drive_collision_blocks_approval(ctx):
    result = await request(ctx)
    ctx.db.add(ProcessedItem(drive_item_id="item", drive_id="other-drive", source="manual"))
    await ctx.db.commit()
    with pytest.raises(HTTPException) as error:
        await service.decide_request(ctx.db, ctx.owner.upn, result.id, True)
    assert error.value.status_code == 409
    assert result.status == "pending"


async def test_request_listing_is_scoped(ctx):
    result = await request(ctx)
    assert await service.list_requests(ctx.db, ctx.outsider) == []
    assert await service.list_requests(ctx.db, ctx.organizer) == []
    assert await service.list_requests(ctx.db, ctx.owner) == [result]
    assert await service.list_requests(ctx.db, ctx.requester) == [result]


async def test_request_route_loads_contract_in_one_query(ctx):
    await request(ctx)
    execute_calls = 0
    original_execute = ctx.db.execute

    async def counted_execute(*args, **kwargs):
        nonlocal execute_calls
        execute_calls += 1
        return await original_execute(*args, **kwargs)

    ctx.db.execute = counted_execute
    rows = await recording_processing_requests.listing(status=None, db=ctx.db, user=ctx.owner)
    assert rows[0]["requester_name"] == ctx.requester.upn
    assert rows[0]["can_decide"] is True
    assert "drive_id" not in rows[0]
    assert execute_calls == 1


async def test_approved_pipeline_preserves_calendar_access_without_emails(ctx, monkeypatch):
    from app.pipeline import steps
    result = await request(ctx)
    await service.decide_request(ctx.db, ctx.owner.upn, result.id, True)
    meeting = await ctx.db.get(Meeting, result.meeting_id)
    meeting.transcript = "[Speaker A] We agreed to complete the project review tomorrow."
    await ctx.db.commit()
    send = AsyncMock()
    monkeypatch.setattr(steps, "_send_ready_for_review", send)
    monkeypatch.setattr(steps, "_send_processing_started", send)
    monkeypatch.setattr(steps, "_send_popia_notice", send)
    await steps.process_recording(ctx.db, "item", result.drive_id, owner_upn=ctx.owner.upn)
    assert meeting.state == "awaiting_review"
    assert meeting.organizer_upn == ctx.organizer.upn
    assert (await service.recent_state(ctx.db, ctx.requester, ctx.event))["action"] == "view"
    participants = list(await ctx.db.scalars(select(MeetingParticipant)))
    assert {p.user_upn for p in participants if p.is_organizer} == {ctx.organizer.upn}
    send.assert_not_awaited()


async def test_own_recording_process_uses_calendar_identity(ctx):
    ctx.scan.side_effect = lambda drive, **kw: [ctx.item] if drive == f"drive:{ctx.requester.upn}" else []
    assert (await service.recent_state(ctx.db, ctx.requester, ctx.event))["action"] == "process"
    result = await service.process_own_event(ctx.db, ctx.requester.upn, ctx.event["id"])
    from uuid import UUID
    job = await ctx.db.get(RecordingJob, UUID(result["job_id"]))
    assert job.owner_upn == ctx.requester.upn
    meeting = await ctx.db.get(Meeting, UUID(result["meeting_id"]))
    assert meeting.organizer_upn == ctx.organizer.upn


async def test_deny_by_nonowner_is_forbidden(ctx):
    result = await request(ctx)
    with pytest.raises(HTTPException) as error:
        await service.decide_request(ctx.db, ctx.requester.upn, result.id, False)
    assert error.value.status_code == 403


async def test_existing_completed_during_pending_reused(ctx):
    result = await request(ctx)
    ctx.db.add(ProcessedItem(drive_item_id="item", drive_id=result.drive_id, source="manual"))
    meeting = Meeting(drive_item_id="item", organizer_upn=ctx.organizer.upn,
                      title=ctx.event["subject"], recorded_at=service.parse_graph_datetime(ctx.event["start"]),
                      state="awaiting_review", transcript="Existing")
    ctx.db.add(meeting)
    await ctx.db.commit()
    await service.decide_request(ctx.db, ctx.owner.upn, result.id, True)
    assert result.meeting_id == meeting.id
    assert not list(await ctx.db.scalars(select(RecordingJob)))
    assert (await service.recent_state(ctx.db, ctx.requester, ctx.event))["action"] == "view"


def test_client_cannot_choose_recording_and_pending_index_is_partial():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        EventReference(event_id="event", drive_id="arbitrary", owner="attacker")
    index = next(i for i in RecordingProcessingRequest.__table__.indexes if i.name == "uq_processing_request_pending")
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE" in sql and "WHERE status = 'pending'" in sql


async def test_calendar_pagination_and_online_filter(monkeypatch):
    monkeypatch.setattr(service.graph.settings, "graph_impl", "microsoft")
    monkeypatch.setattr(service.graph, "_headers", lambda: {})
    url = service.graph.settings.graph_base + "/next-page"
    responses = [{"value": [{"id": "online", "isOnlineMeeting": True}], "@odata.nextLink": url},
                 {"value": [{"id": "offline", "isOnlineMeeting": False}]}]
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, target, **kw):
            return httpx.Response(200, json=responses[1 if target == url else 0], request=httpx.Request("GET", target))
    monkeypatch.setattr(service.graph.httpx, "AsyncClient", lambda **kw: Client())
    assert len(await service.graph.get_upcoming_calendar_events("user", include_offline=True)) == 2
    assert len(await service.graph.get_upcoming_calendar_events("user")) == 1
