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
