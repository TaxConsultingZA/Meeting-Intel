from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.models import ProcessedItem, Meeting, ProcessingState
from app.models import RecordingJob
from app.services import recording_identity as identity
from app.api import recordings
from app.tests.test_cross_user_recordings import ctx


def ledger(ctx):
    row = ProcessedItem(drive_item_id="item", drive_id=f"drive:{ctx.owner.upn}", filename=None, source="reconcile")
    ctx.session.add(row)
    ctx.owner.graph_drive_id = row.drive_id
    ctx.session.commit()
    return row


async def test_unknown_filename_resolution_updates_response_without_mutating_history(ctx, monkeypatch):
    row = ledger(ctx)
    rows = await recordings.available_recordings(ctx.db, ctx.owner.upn, resolve_filenames=True)
    assert rows[0]["name"] == ctx.item["name"]
    assert rows[0]["calendar_matched"] is False
    assert row.filename is None


async def test_independent_choice_preserves_completed_results_and_cancelled_history(ctx):
    row = ledger(ctx)
    meeting = Meeting(drive_item_id="item", title="Wrong calendar title", state=ProcessingState.awaiting_review,
                      transcript="preserve transcript", summary="preserve summary",
                      extracted_json={"outlook_event_id":"wrong", "summary":"preserve"})
    ctx.session.add(meeting)
    ctx.session.commit()
    before = deepcopy(meeting.extracted_json)
    await identity.choose_association(ctx.db, ctx.owner, row.drive_id, "item", None)
    await ctx.db.commit()
    assert row.identity_json["status"] == "independent"
    assert meeting.extracted_json == before
    assert meeting.transcript == "preserve transcript"
    assert meeting.summary == "preserve summary"
    result = (await recordings.available_recordings(ctx.db, ctx.owner.upn))[0]
    assert result["name"] == ctx.item["name"]
    assert result["calendar_matched"] is False
    assert result["meeting_state"] == ProcessingState.awaiting_review
    assert result["meeting_id"] == str(meeting.id)


async def test_manual_link_requires_owner_and_calendar_stable_id(ctx):
    row = ledger(ctx)
    with pytest.raises(HTTPException) as denied:
        await identity.choose_association(ctx.db, ctx.outsider, row.drive_id, "item", ctx.event["id"])
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as invalid:
        await identity.choose_association(ctx.db, ctx.owner, row.drive_id, "item", "made-up-event")
    assert invalid.value.status_code == 422
    await identity.choose_association(ctx.db, ctx.owner, row.drive_id, "item", ctx.event["id"])
    assert row.identity_json["event"]["id"] == ctx.event["id"]
    assert row.identity_json["event"]["iCalUId"] == ctx.event["iCalUId"]
    assert row.identity_json["status"] == "linked"
    assert await recordings.available_recordings(ctx.db, ctx.outsider.upn) == []


async def test_calendar_permission_error_is_diagnostic_and_not_empty_success(ctx, monkeypatch):
    row = ledger(ctx)
    monkeypatch.setattr(identity.graph, "get_calendar_window", AsyncMock(side_effect=RuntimeError("SECRET")))
    with pytest.raises(HTTPException) as error:
        await identity.calendar_choices(ctx.db, ctx.owner, row.drive_id, "item")
    assert error.value.status_code == 502
    assert "SECRET" not in error.value.detail


@pytest.mark.parametrize("status,blocked", [("pending",True),("processing",True),("cancelled",False),("completed",False)])
async def test_association_keeps_task_history_and_blocks_only_active_jobs(ctx,status,blocked):
    row=ledger(ctx)
    job=RecordingJob(drive_item_id="item",drive_id=row.drive_id,owner_upn=ctx.owner.upn,status=status,source="manual")
    ctx.session.add(job)
    ctx.session.commit()
    if blocked:
        with pytest.raises(HTTPException) as error:
            await identity.choose_association(ctx.db,ctx.owner,row.drive_id,"item",None)
        assert error.value.status_code==409
    else:
        await identity.choose_association(ctx.db,ctx.owner,row.drive_id,"item",None)
    assert job.status==status


async def test_owner_discovery_is_idempotent_and_does_not_process_files(ctx,monkeypatch):
    monkeypatch.setattr(recordings.graph,"list_recordings_folder",AsyncMock(return_value=[ctx.item]))
    monkeypatch.setattr(recordings,"record_sync_result",AsyncMock())
    first=await recordings.discover_own_recordings(ctx.db,ctx.owner)
    second=await recordings.discover_own_recordings(ctx.db,ctx.owner)
    assert first=={"discovered":1,"failed":0,"status":"success"}
    assert second["discovered"]==0
    from sqlalchemy import select
    assert list(await ctx.db.scalars(select(RecordingJob)))==[]
    recordings.graph.list_recordings_folder.assert_awaited_with(f"drive:{ctx.owner.upn}",strict=True)

def test_teams_evidence_does_not_fabricate_calendar_event():
    row = ProcessedItem(drive_item_id="item", drive_id="owned", source="test", filename="actual.mp4")
    row.identity_json = {"status":"unmatched", "recorded_at":"2026-10-22T06:50:32Z", "teams_meeting":{
        "verified":True,"title":"Teams title","meeting_id":"thread-id", "recording_reference":"recording-message-id",
        "drive_id":"owned","drive_item_id":"item"}}
    actual = identity.display_identity(row)
    assert actual["teams_meeting_verified"] is True
    assert actual["calendar_matched"] is False
    assert "Outlook event ID" in actual["identity_reason"]
    row.identity_json["teams_meeting"]["drive_item_id"] = "other-file"
    assert identity.display_identity(row)["teams_meeting_verified"] is False


def test_title_or_status_without_event_id_is_not_a_calendar_link():
    row = ProcessedItem(drive_item_id="item",drive_id="owned",source="test")
    row.identity_json={"status":"linked","event":{"subject":"Trust"}}
    assert identity.display_identity(row)["calendar_matched"] is False
    row.identity_json={}
    assert identity.display_identity(row,{"t5_calendar_event":True})["calendar_matched"] is False


async def test_list_orders_real_instants_missing_last_and_preserves_owner_scope(ctx):
    row=ledger(ctx)
    row.filename="older.mp4"
    row.identity_json={"recorded_at":"2026-09-01T08:41:58Z"}
    for item_id,drive,name,instant in [
        ("latest",row.drive_id,"latest.mp4","2026-10-22T14:50:32+08:00"),
        ("unknown",row.drive_id,"unknown.mp4",None),
        ("foreign","unrelated-drive","private.mp4","2026-12-01T08:00:00Z")]:
        ctx.session.add(ProcessedItem(drive_item_id=item_id,drive_id=drive,filename=name,source="test",identity_json={"recorded_at":instant}))
    ctx.session.commit()
    actual=await recordings.available_recordings(ctx.db,ctx.owner.upn)
    assert [r["drive_item_id"] for r in actual]==["latest","item","unknown"]
    assert actual[0]["created_at"]=="2026-10-22T06:50:32Z"
    assert actual[-1]["created_at"] is None

async def test_authorized_review_uses_file_display_time_and_preserves_old_results(ctx):
    from app.api.reviews import _with_recording_display
    from app.schemas import MeetingOut
    from datetime import datetime, timezone
    row=ledger(ctx)
    row.filename="Test-20260901_164158.mp4"
    row.identity_json={"status":"needs_review","recorded_at":"2026-09-01T08:41:58Z"}
    meeting=Meeting(drive_item_id="item",title="Trust",recorded_at=datetime(2026,9,1,8,tzinfo=timezone.utc),state=ProcessingState.awaiting_review,transcript="retained",summary="retained")
    ctx.session.add(meeting);ctx.session.commit()
    output=MeetingOut(id=str(meeting.id),title=meeting.title,state=meeting.state,summary=meeting.summary,recorded_at=meeting.recorded_at,action_items=[])
    result=(await _with_recording_display(ctx.db,[meeting],[output]))[0]
    assert result.recording_display["recorded_at"]=="2026-09-01T08:41:58Z"
    assert result.recording_display["calendar_matched"] is False
    assert meeting.title=="Trust" and meeting.transcript=="retained" and meeting.summary=="retained"
    assert meeting.recorded_at.hour==8 and meeting.recorded_at.minute==0

async def test_teams_verification_reaches_owner_list_without_calendar_link_or_history_writes(ctx):
 row=ledger(ctx)
 row.filename="actual.mp4"
 row.identity_json={"status":"unmatched","recorded_at":"2026-10-22T06:50:32Z","teams_meeting":{
  "verified":True,"title":"Teams actual","meeting_id":"thread-id","recording_reference":"message-id",
  "drive_id":row.drive_id,"drive_item_id":row.drive_item_id}}
 ctx.session.commit()
 before=deepcopy(row.identity_json)
 actual=(await recordings.available_recordings(ctx.db,ctx.owner.upn))[0]
 assert actual["teams_meeting_verified"] and actual["teams_meeting_title"]=="Teams actual"
 assert actual["calendar_matched"] is False and actual["original_filename"]=="actual.mp4"
 assert row.identity_json==before
