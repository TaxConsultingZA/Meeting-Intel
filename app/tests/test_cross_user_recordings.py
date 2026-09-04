"""Offline T5 service/route tests using real SQLAlchemy rows in memory.

SQLite is only a test adapter; PostgreSQL constraints are separately compiled.
No Graph, transcription, mail, or staging database connections are permitted.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex
from sqlalchemy.dialects import postgresql

from app.models import Base, RegisteredUser, RecordingJob, Meeting, MeetingParticipant, RecordingProcessingRequest, ProcessedItem
from app.services import cross_user_recordings as service
from app.api import calendar
from app.api.recording_processing_requests import EventReference, public_request


@compiles(JSONB, "sqlite")
def sqlite_json(type_, compiler, **kwargs):
    return "JSON"


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
    session.add_all(users)
    session.commit()
    requester, owner, organizer, outsider = users
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
                          organizer=organizer, outsider=outsider, event=event, item=item, scan=scan)
    session.close()
    engine.dispose()


async def request(ctx):
    return await service.create_request(ctx.db, ctx.requester.upn, ctx.event["id"])


async def test_recent_ended_window_and_upcoming_unchanged(ctx, monkeypatch):
    now = datetime.now(timezone.utc)
    events = []
    for name, offset in [("recent", -1), ("old", -24*8), ("ongoing", 1), ("future", 24)]:
        event = deepcopy(ctx.event)
        event["id"] = name
        event["end"]["dateTime"] = (now+timedelta(hours=offset)).isoformat()
        event["start"]["dateTime"] = (now+timedelta(hours=offset-2)).isoformat()
        events.append(event)
    monkeypatch.setattr(service.graph, "get_upcoming_calendar_events", AsyncMock(return_value=events))
    monkeypatch.setattr(service, "recent_state", AsyncMock(return_value={"action": "no_recording"}))
    monkeypatch.setattr(calendar, "record_sync_result", AsyncMock())
    recent = await calendar.recent_meetings(ctx.db, ctx.requester.upn)
    assert [r["event_id"] for r in recent] == ["recent"]
    assert recent[0]["status"] == "ended"
    upcoming = await calendar.upcoming_meetings(7, ctx.db, ctx.requester.upn)
    assert len(upcoming) == 4  # Existing API contract untouched; frontend filters ended ones.
    assert calendar._event_status(events[2]["start"]["dateTime"], events[2]["end"]["dateTime"]) == "in_progress"


async def test_nonparticipant_forbidden(ctx):
    with pytest.raises(HTTPException) as error:
        await service.create_request(ctx.db, ctx.outsider.upn, ctx.event["id"])
    assert error.value.status_code == 403
    ctx.scan.assert_not_awaited()


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
