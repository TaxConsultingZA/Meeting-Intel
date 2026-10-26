"""User-scoped calendar -> incremental discovery -> conservative matching.

Only ledger display identity and calendar cache change. No processing jobs,
meeting results, review history or participant access are rewritten.
"""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.graph import client as graph
from app.models import RegisteredUser, UserSyncState, ProcessedItem, SyncedCalendarEvent, RecordingJob
from app.services.meeting_matching import recording_datetime, match_calendar_event, event_people
from app.services.recording_identity import event_snapshot
from app.utils.timezones import parse_graph_datetime, utc_iso

STAGES = ("calendar", "discovery", "matching")
MAX_DELTA_PAGES = 12
MAX_HISTORICAL_WINDOWS = 4
MAX_METADATA_READS = 12
COOLDOWN = timedelta(seconds=60)


async def store_events_batched(db, upn, events):
    """One cache lookup per window, not a database round-trip per calendar item."""
    unique = {e["id"]: e for e in events if e.get("id")}
    existing = {r.event_id:r for r in await db.scalars(select(SyncedCalendarEvent).where(
        SyncedCalendarEvent.user_upn==upn, SyncedCalendarEvent.event_id.in_(list(unique))))}
    created = 0
    for event_id,raw in unique.items():
        row=existing.get(event_id)
        if row is None:
            row=SyncedCalendarEvent(user_upn=upn,event_id=event_id,raw=raw)
            db.add(row);created+=1
        row.subject=raw.get("subject")
        row.starts_at=parse_graph_datetime(raw.get("start"))
        row.ends_at=parse_graph_datetime(raw.get("end"))
        row.raw=raw
        row.last_synced_at=datetime.now(timezone.utc)
    await db.flush()
    return created,len(unique)-created


async def state_for(db, upn, stage):
    source = f"recording_{stage}"
    state = await db.scalar(select(UserSyncState).where(
        UserSyncState.user_upn == upn, UserSyncState.source == source))
    if state is None:
        state = UserSyncState(user_upn=upn, source=source, status="never", details_json={})
        db.add(state)
        await db.flush()
    return state


def public_state(state, stage):
    details = state.details_json or {}
    # Never return opaque Graph continuation URLs to browsers/logs.
    return {"stage": stage, "status": state.status,
            "last_attempted_at": utc_iso(state.last_attempted_at.isoformat()) if state.last_attempted_at else None,
            "last_succeeded_at": utc_iso(state.last_succeeded_at.isoformat()) if state.last_succeeded_at else None,
            "error": state.last_error, "counts": details.get("counts", {})}


async def get_status(db, upn):
    rows = list(await db.scalars(select(UserSyncState).where(
        UserSyncState.user_upn == upn, UserSyncState.source.in_([f"recording_{s}" for s in STAGES]))))
    by_source = {r.source: r for r in rows}
    return [public_state(by_source[f"recording_{s}"], s) if f"recording_{s}" in by_source
            else {"stage":s,"status":"never","counts":{},"last_succeeded_at":None,"last_attempted_at":None,"error":None}
            for s in STAGES]


async def update_file(db, drive_id, item, *, records=None, flush=True):
    if (item.get("deleted") is not None or item.get("folder") is not None or item.get("remoteItem")
            or not str(item.get("name","")).lower().endswith(".mp4")):
        return False
    item_id = item.get("id")
    parent = item.get("parentReference") or {}
    if not item_id or (parent.get("driveId") and parent["driveId"] != drive_id):
        return False
    ledger = records.get(item_id) if records is not None else await db.scalar(select(ProcessedItem).where(ProcessedItem.drive_item_id == item_id))
    created = ledger is None
    if ledger is None:
        ledger = ProcessedItem(drive_item_id=item_id, drive_id=drive_id, source="recording_update")
        db.add(ledger)
        if records is not None:
            records[item_id]=ledger
    elif ledger.drive_id != drive_id:
        raise RuntimeError("Recording drive identity conflict")
    identity = dict(ledger.identity_json or {})
    ledger.filename, ledger.etag = item["name"], item.get("eTag")
    instant = recording_datetime(item["name"], item)
    identity.update({"size":item.get("size"), "recorded_at":instant.isoformat() if instant else identity.get("recorded_at"),
                     "folder_id":parent.get("id"), "metadata_status":"available"})
    identity.setdefault("status", "unmatched")
    ledger.identity_json = identity
    if flush:
        await db.flush()
    return created


def strong_match(filename, instant, events, upn):
    # A unique exact title + actual occurrence time + stable event identity +
    # owner participation is required. Fuzzy or cancelled events are not evidence.
    candidates = [e for e in events if not e.get("isCancelled") and e.get("id") and e.get("iCalUId")
                  and upn.lower() in event_people(e)[0]]
    match = match_calendar_event(filename, instant, candidates)
    if match is None or instant is None:
        return None
    start, end = parse_graph_datetime(match.get("start")), parse_graph_datetime(match.get("end"))
    return match if start and end and start <= instant <= end + timedelta(minutes=10) else None


async def run_stage(db, user, stage):
    if stage not in STAGES:
        raise HTTPException(404, "Unknown update step")
    # Serialize submissions across API replicas using the existing user row.
    try:
        user = await db.scalar(select(RegisteredUser).where(
            RegisteredUser.id == user.id, RegisteredUser.is_subscribed.is_(True)).with_for_update(nowait=True))
    except DBAPIError as error:
        await db.rollback()
        if getattr(error.orig,"sqlstate",None) != "55P03":
            raise
        raise HTTPException(409, "An update is already running") from None
    if user is None:
        raise HTTPException(403, "Subscribe before updating meetings and recordings")
    upn = user.upn
    state = await state_for(db, user.upn, stage)
    now = datetime.now(timezone.utc)
    attempted = state.last_attempted_at
    if attempted and attempted.tzinfo is None:
        attempted = attempted.replace(tzinfo=timezone.utc)
    if attempted and now-attempted < COOLDOWN and state.status == "success":
        return public_state(state, stage)
    details = deepcopy(state.details_json or {})
    try:
        if stage == "calendar":
            events = await graph.get_calendar_window(user.upn,now-timedelta(days=30),now+timedelta(days=14),max_pages=6)
            created, updated = await store_events_batched(db,user.upn,events)
            counts, complete = {"events":len(events),"created":created,"updated":updated}, True
        elif stage == "discovery":
            drive_id = await graph.get_user_drive_id(user.upn)
            if details.get("drive_id") != drive_id:
                details = {"drive_id":drive_id}
            roots = details.get("roots")
            checked = parse_graph_datetime(details.get("roots_checked_at"))
            if roots is None or details.get("roots_version") != 2 or checked is None or now-checked > timedelta(days=1):
                roots = await graph.recording_roots(drive_id)
                details.update(roots=roots, roots_checked_at=now.isoformat(), roots_version=2)
            cursors = dict(details.get("cursors",{}))
            found = changed = pages = 0
            complete = True
            for folder in roots:
                if pages >= MAX_DELTA_PAGES:
                    complete = False
                    break
                items, cursor, done, calls = await graph.recording_delta(
                    drive_id, folder, cursors.get(folder), MAX_DELTA_PAGES-pages)
                records={r.drive_item_id:r for r in await db.scalars(select(ProcessedItem).where(
                    ProcessedItem.drive_item_id.in_([item["id"] for item in items if item.get("id")])))}
                for item in items:
                    found += int(await update_file(db, drive_id, item,records=records,flush=False))
                    changed += int(str(item.get("name","")).lower().endswith(".mp4") and item.get("deleted") is None)
                await db.flush()
                # Cursor and file writes commit in the same transaction.
                cursors[folder], pages = cursor, pages+calls
                complete = complete and done
            details["cursors"] = cursors
            user.graph_drive_id = drive_id
            counts = {"new":found,"changed":changed,"pages":pages,"folders":len(roots)}
        else:
            if not user.graph_drive_id:
                raise RuntimeError("Recording discovery has not established your drive")
            ledgers = list(await db.scalars(select(ProcessedItem).where(ProcessedItem.drive_id==user.graph_drive_id)))
            # Legacy discovery saved neither filename nor file timestamp. Repair
            # metadata with bounded exact GETs, continuing on the next update.
            repaired = unavailable = 0
            for ledger in ledgers:
                meta = ledger.identity_json or {}
                if (not ledger.filename or not meta.get("recorded_at") or meta.get("size") is None) and repaired+unavailable < MAX_METADATA_READS:
                    try:
                        item = await graph.get_drive_item(ledger.drive_id, ledger.drive_item_id)
                        if item.get("id") != ledger.drive_item_id:
                            raise RuntimeError("File identity mismatch")
                        await update_file(db,ledger.drive_id,item)
                        repaired += 1
                    except Exception as error:
                        unavailable += 1
                        ledger.identity_json = dict(meta,metadata_status="unavailable",
                            metadata_error="Unable to read file metadata",
                            metadata_http_status=getattr(getattr(error,"response",None),"status_code",None))
            weeks = {}
            for ledger in ledgers:
                instant = parse_graph_datetime((ledger.identity_json or {}).get("recorded_at"))
                if instant:
                    start = (instant-timedelta(days=instant.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
                    weeks[start.isoformat()] = start
            coverage = dict(details.get("coverage",{}))
            windows = failed_windows = 0
            pending = []
            for key,start in sorted(weeks.items()):
                last = parse_graph_datetime(coverage.get(key))
                if last and now-last < timedelta(days=1):
                    continue
                if len(pending) >= MAX_HISTORICAL_WINDOWS:
                    break
                pending.append((key,start))
            semaphore=asyncio.Semaphore(2)
            async def read_window(start):
                async with semaphore:
                    return await graph.get_calendar_window(user.upn,start-timedelta(hours=3),
                        start+timedelta(days=7,hours=3),max_pages=6)
            window_results=await asyncio.gather(*(read_window(start) for _,start in pending),return_exceptions=True)
            failed_keys=set()
            for (key,_),response in zip(pending,window_results):
                if isinstance(response,BaseException):
                    failed_windows+=1;failed_keys.add(key)
                    continue
                await store_events_batched(db,user.upn,response)
                coverage[key]=now.isoformat();windows+=1
            details["coverage"] = coverage
            events = [r.raw for r in await db.scalars(select(SyncedCalendarEvent).where(SyncedCalendarEvent.user_upn==user.upn))]
            active = set(await db.scalars(select(RecordingJob.drive_item_id).where(
                RecordingJob.owner_upn==user.upn,RecordingJob.status.in_(("pending","processing")))))
            linked = unresolved = 0
            for ledger in ledgers:
                if ledger.drive_item_id in active:
                    continue
                meta = dict(ledger.identity_json or {})
                instant=parse_graph_datetime(meta.get("recorded_at"))
                week=(instant-timedelta(days=instant.weekday())).replace(hour=0,minute=0,second=0,microsecond=0).isoformat() if instant else None
                if week in failed_keys:
                    linked+=int(meta.get("status")=="linked")
                    unresolved+=int(meta.get("status")!="linked")
                    continue
                if meta.get("decided_by"):  # Preserve prior explicit owner decisions.
                    linked += int(meta.get("status")=="linked")
                    unresolved += int(meta.get("status")!="linked")
                    continue
                match = strong_match(ledger.filename or "",parse_graph_datetime(meta.get("recorded_at")),events,user.upn)
                meta.update(status="linked" if match else "unmatched",event=event_snapshot(match) if match else None,
                            evaluated_at=now.isoformat(),evidence="unique_exact_title_time_owner_stable_id" if match else "insufficient")
                ledger.identity_json = meta
                linked += int(match is not None)
                unresolved += int(match is None)
            counts = {"linked":linked,"unresolved":unresolved,"metadata_repaired":repaired,
                      "metadata_unavailable":unavailable,"calendar_windows":windows,
                      "calendar_windows_failed":failed_windows,"active_skipped":len(active)}
            complete = all(coverage.get(key) for key in weeks) and not unavailable and not failed_windows and not any(
                not r.filename or not (r.identity_json or {}).get("recorded_at") for r in ledgers)
        state.details_json = dict(details, counts=counts)
        state.status, state.last_attempted_at = "success" if complete else "partial", now
        state.last_error = None if complete else "Some data remains pending. Update again to continue safely."
        if complete:
            state.last_succeeded_at = now
        await db.commit()
        return public_state(state,stage)
    except Exception as error:
        await db.rollback()
        state = await state_for(db,upn,stage)
        state.status, state.last_attempted_at = "failed", now
        code = getattr(getattr(error,"response",None),"status_code",None)
        state.last_error = f"{stage} failed"+(f" (Microsoft HTTP {code})" if code else "")+". Previous saved data is retained; retry the update."
        await db.commit()
        return public_state(state,stage)
