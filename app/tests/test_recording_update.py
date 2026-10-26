from datetime import datetime, timezone, timedelta
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from app.tests.test_cross_user_recordings import ctx
from app.models import ProcessedItem, RecordingJob, Meeting, ProcessingState, UserSyncState
from app.services import recording_update as update
from app.api.recordings import available_recordings
from app.utils.timezones import utc_iso


@pytest.fixture
def io(ctx,monkeypatch):
    ctx.item["size"]=544023
    ctx.item["parentReference"]={"driveId":f"drive:{ctx.owner.upn}","id":"folder"}
    monkeypatch.setattr(update.graph,"recording_roots",AsyncMock(return_value=["folder"]))
    delta=AsyncMock(return_value=([ctx.item],"delta-1",True,1))
    monkeypatch.setattr(update.graph,"recording_delta",delta)
    monkeypatch.setattr(update.graph,"get_calendar_window",AsyncMock(return_value=[ctx.event]))
    return delta


async def test_update_stages_discover_once_checkpoint_and_preserve_all_results(ctx,io):
    meeting=Meeting(drive_item_id="item",title="Wrong legacy title",state=ProcessingState.awaiting_review,
                    transcript="keep transcript",summary="keep summary",extracted_json={"outlook_event_id":"wrong"})
    job=RecordingJob(drive_item_id="item",drive_id=f"drive:{ctx.owner.upn}",owner_upn=ctx.owner.upn,status="cancelled",source="manual")
    ctx.session.add_all([meeting,job]);ctx.session.commit()
    before=deepcopy(meeting.extracted_json)
    results=[await update.run_stage(ctx.db,ctx.owner,s) for s in update.STAGES]
    assert all(r["status"]=="success" for r in results)
    assert results[1]["counts"]["new"]==1
    assert results[2]["counts"]["linked"]==1
    row=(await available_recordings(ctx.db,ctx.owner.upn))[0]
    assert row["name"]==ctx.item["name"] and row["calendar_matched"]
    assert row["created_at"].endswith("Z") and row["size"]==544023
    assert meeting.title=="Wrong legacy title" and meeting.extracted_json==before
    assert (meeting.transcript,meeting.summary,meeting.state,job.status)==("keep transcript","keep summary",ProcessingState.awaiting_review,"cancelled")
    await update.run_stage(ctx.db,ctx.owner,"discovery")
    assert io.await_count==1  # Server cooldown, not another Graph sweep.
    assert len(list(await ctx.db.scalars(select(ProcessedItem))))==1
    state=await update.state_for(ctx.db,ctx.owner.upn,"discovery")
    assert state.details_json["cursors"]=={"folder":"delta-1"}
    assert "delta-1" not in str(await update.get_status(ctx.db,ctx.owner.upn))
    assert await available_recordings(ctx.db,ctx.outsider.upn)==[]


async def test_partial_calendar_failure_does_not_prevent_discovery_or_hide_previous_success(ctx,io,monkeypatch):
    await update.run_stage(ctx.db,ctx.owner,"calendar")
    state=await update.state_for(ctx.db,ctx.owner.upn,"calendar")
    previous=state.last_succeeded_at
    state.last_attempted_at-=timedelta(minutes=2);ctx.session.commit()
    monkeypatch.setattr(update.graph,"get_calendar_window",AsyncMock(side_effect=RuntimeError("SECRET")))
    result=await update.run_stage(ctx.db,ctx.owner,"calendar")
    assert result["status"]=="failed" and "SECRET" not in result["error"]
    assert result["last_succeeded_at"]==utc_iso(previous.isoformat())
    assert (await update.run_stage(ctx.db,ctx.owner,"discovery"))["counts"]["new"]==1


async def test_incremental_continuation_uses_checkpoint_and_never_duplicates(ctx,io):
    io.side_effect=[([ctx.item],"page-2",False,12),([ctx.item],"finished",True,1)]
    first=await update.run_stage(ctx.db,ctx.owner,"discovery")
    assert first["status"]=="partial" and first["last_succeeded_at"] is None
    second=await update.run_stage(ctx.db,ctx.owner,"discovery")
    assert second["status"]=="success" and second["counts"]["new"]==0
    assert io.await_args.args[2]=="page-2"
    assert len(list(await ctx.db.scalars(select(ProcessedItem))))==1


async def test_historical_unknown_gets_real_filename_and_missing_date_never_invents_time(ctx,io,monkeypatch):
    ctx.owner.graph_drive_id=f"drive:{ctx.owner.upn}"
    ctx.session.add(ProcessedItem(drive_item_id="item",drive_id=ctx.owner.graph_drive_id,source="manual"))
    ctx.session.commit()
    result=await update.run_stage(ctx.db,ctx.owner,"matching")
    row=(await available_recordings(ctx.db,ctx.owner.upn))[0]
    assert row["name"]==ctx.item["name"] and row["created_at"] is not None
    ledger=await ctx.db.scalar(select(ProcessedItem))
    ledger.identity_json={};ctx.item.pop("createdDateTime");ctx.session.commit()
    state=await update.state_for(ctx.db,ctx.owner.upn,"matching");state.last_attempted_at-=timedelta(minutes=2);ctx.session.commit()
    result=await update.run_stage(ctx.db,ctx.owner,"matching")
    assert result["status"]=="partial"
    assert (await available_recordings(ctx.db,ctx.owner.upn))[0]["created_at"] is None


def test_strong_match_requires_exact_title_stable_id_owner_and_unique_occurrence(ctx):
    instant=datetime.fromisoformat(ctx.item["createdDateTime"])
    assert update.strong_match(ctx.item["name"],instant,[ctx.event],ctx.owner.upn)
    for field,value in [("subject","Project Preview"),("iCalUId",None),("isCancelled",True)]:
        changed=dict(ctx.event,**{field:value})
        assert update.strong_match(ctx.item["name"],instant,[changed],ctx.owner.upn) is None
    other=deepcopy(ctx.event);other["id"]="another";other["iCalUId"]="another"
    assert update.strong_match(ctx.item["name"],instant,[ctx.event,other],ctx.owner.upn) is None
    assert update.strong_match(ctx.item["name"],instant,[ctx.event],ctx.outsider.upn) is None


async def test_historical_read_failure_saves_metadata_but_does_not_guess_calendar(ctx,io,monkeypatch):
    await update.run_stage(ctx.db,ctx.owner,"discovery")
    monkeypatch.setattr(update.graph,"get_calendar_window",AsyncMock(side_effect=RuntimeError("SECRET")))
    result=await update.run_stage(ctx.db,ctx.owner,"matching")
    assert result["status"]=="partial"
    assert result["counts"]["calendar_windows_failed"]==1
    row=(await available_recordings(ctx.db,ctx.owner.upn))[0]
    assert row["name"]==ctx.item["name"] and row["created_at"] and not row["calendar_matched"]
