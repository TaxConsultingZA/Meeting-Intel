"""Calendar-bound discovery and owner approval. No client-supplied recording IDs."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re

from fastapi import HTTPException
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from app.graph import client as graph
from app.models import (RegisteredUser, Meeting, MeetingParticipant, ProcessedItem,
                        RecordingJob, RecordingProcessingRequest, ProcessingState)
from app.services.jobs import enqueue_recording_job, ACTIVE_JOB_STATUSES
from app.services.meeting_matching import clean_recording_title, recording_datetime, match_calendar_event, event_people
from app.utils.timezones import parse_graph_datetime, utc_iso


DONE = (ProcessingState.awaiting_review, ProcessingState.approved, ProcessingState.sent)


def people(event):
    # Resources and explicitly declined invitations are not human participants.
    event = dict(event)
    event["attendees"] = [a for a in event.get("attendees", [])
                          if a.get("type") != "resource"
                          and (a.get("status") or {}).get("response") != "declined"]
    return event_people(event)[0]


def organizer(event):
    return ((event.get("organizer") or {}).get("emailAddress", {}).get("address") or "").strip().lower()


def occurrence_key(event):
    return sha256("|".join([event.get("iCalUId") or event.get("id", ""),
                           utc_iso(event.get("start")) or "", organizer(event)]).encode()).hexdigest()


def snapshot(event):
    return {k: event.get(k) for k in ("id", "iCalUId", "subject", "start", "end", "organizer", "attendees")}


def recent_event(event, now=None):
    now = now or datetime.now(timezone.utc)
    end = parse_graph_datetime(event.get("end"))
    start = parse_graph_datetime(event.get("start"))
    return bool(start and end and start < end and now - timedelta(days=7) <= end < now
                and not event.get("isCancelled")
                and not (event.get("subject") or "").lower().startswith("canceled:"))


def validate_participant(event, upn):
    if not event or event.get("isCancelled") or upn.strip().lower() not in people(event):
        raise HTTPException(403, "Not an organizer or Calendar attendee")
    if not organizer(event) or not parse_graph_datetime(event.get("start")) or not parse_graph_datetime(event.get("end")):
        raise HTTPException(409, "Calendar identity or time unavailable")


async def read_event(upn, event_id, *, recent=False):
    try:
        event = await graph.get_calendar_event(upn, event_id)
    except Exception as exc:
        raise HTTPException(502, "Calendar unavailable; no processing authorized") from exc
    validate_participant(event, upn)
    if recent and not recent_event(event):
        raise HTTPException(409, "Only ended meetings from the past seven days can be processed here")
    return event


def normal_title(title):
    return " ".join(re.findall(r"[^\W_]+", title.casefold()))


def strict_match(item, event):
    """Conservative wrapper: exact cleaned title, bounded UTC time; never rank ties."""
    instant = recording_datetime(item.get("name", ""), item)
    start, end = parse_graph_datetime(event.get("start")), parse_graph_datetime(event.get("end"))
    return bool(item.get("id") and item.get("name", "").lower().endswith(".mp4")
                and instant and start and end and start < end
                and start - timedelta(minutes=5) <= instant <= end + timedelta(minutes=30)
                and normal_title(clean_recording_title(item["name"])) == normal_title(event.get("subject") or "")
                and match_calendar_event(item["name"], instant, [event]))


def same_occurrence(a, b):
    return bool(a.get("iCalUId") and a.get("iCalUId") == b.get("iCalUId")
                and utc_iso(a.get("start")) == utc_iso(b.get("start"))
                and utc_iso(a.get("end")) == utc_iso(b.get("end"))
                and organizer(a) == organizer(b))


async def scan_owner(owner, event, requester_upn):
    validate_participant(event, owner.upn)
    start, end = parse_graph_datetime(event["start"]), parse_graph_datetime(event["end"])
    events = await graph.get_calendar_window(owner.upn, start - timedelta(hours=1), end + timedelta(hours=1))
    copies = [e for e in events if same_occurrence(event, e) and not e.get("isCancelled")]
    if len(copies) != 1 or requester_upn.lower() not in people(copies[0]) or owner.upn.lower() not in people(copies[0]):
        return []
    drive_id = await graph.get_user_drive_id(owner.upn)
    items = await graph.list_recordings_folder(drive_id, strict=True)
    candidates = []
    for item in items:
        if item.get("remoteItem"):
            continue  # A shared shortcut is not a recording owned by this drive.
        if not strict_match(item, event):
            continue
        matches = {occurrence_key(e) for e in events if strict_match(item, e)}
        if matches != {occurrence_key(event)}:
            raise HTTPException(409, "Ambiguous recording match")
        candidates.append((owner, drive_id, item))
    return candidates


async def verify_item(drive, item, event):
    try:
        current = await graph.get_drive_item(drive, item["id"])
    except Exception as exc:
        raise HTTPException(502, "Recording unavailable; no processing authorized") from exc
    parent_drive = (current.get("parentReference") or {}).get("driveId")
    if (current.get("id") != item["id"] or current.get("remoteItem")
            or (parent_drive and parent_drive != drive) or not strict_match(current, event)):
        raise HTTPException(409, "Recording ownership or reliable match changed")
    return current


async def discover(db, requester, event):
    validate_participant(event, requester.upn)
    owners = list(await db.scalars(select(RegisteredUser).where(
        RegisteredUser.is_subscribed.is_(True), RegisteredUser.upn.in_(people(event)))))
    # Own recordings have product priority; failures cannot silently fall through.
    for group in ([u for u in owners if u.id == requester.id], [u for u in owners if u.id != requester.id]):
        found = []
        for owner in group:
            try:
                found.extend(await scan_owner(owner, event, requester.upn))
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(502, "Recording discovery unavailable") from exc
        if len(found) > 1:
            raise HTTPException(409, "Ambiguous recording match")
        if found:
            return found[0]
    raise HTTPException(404, "No reliable recording found")


async def user_by_upn(db, upn, *, lock=False):
    query = select(RegisteredUser).where(RegisteredUser.upn == upn)
    user = await db.scalar(query.with_for_update() if lock else query)
    if not user:
        raise HTTPException(403, "Registered user required")
    return user


async def visible_result(db, upn, event):
    meetings = list(await db.scalars(select(Meeting).join(MeetingParticipant).where(
        MeetingParticipant.user_upn == upn, Meeting.state.in_(DONE))))
    matches = []
    for meeting in meetings:
        meta = meeting.extracted_json or {}
        bound = meta.get("calendar_occurrence_key") == occurrence_key(event)
        legacy = (normal_title(meeting.title or "") == normal_title(event.get("subject") or "")
                  and utc_iso(meeting.recorded_at.isoformat() if meeting.recorded_at else None) == utc_iso(event.get("start"))
                  and (meeting.organizer_upn or "").lower() == organizer(event))
        if bound or legacy:
            matches.append(meeting)
    return matches[0] if len(matches) == 1 else None


async def recording_state(db, drive_id, item_id):
    # Legacy tables key by item ID alone. Reject cross-drive collisions, never reuse them.
    ledger = await db.scalar(select(ProcessedItem).where(ProcessedItem.drive_item_id == item_id))
    if ledger and ledger.drive_id != drive_id:
        raise HTTPException(409, "Recording drive identity conflict")
    jobs = list(await db.scalars(select(RecordingJob).where(RecordingJob.drive_item_id == item_id)
                                .order_by(RecordingJob.created_at.desc())))
    if any(j.drive_id != drive_id for j in jobs):
        raise HTTPException(409, "Recording drive identity conflict")
    meeting = await db.scalar(select(Meeting).where(Meeting.drive_item_id == item_id))
    if meeting and not ledger:
        raise HTTPException(409, "Recording drive identity unavailable")
    active = next((j for j in jobs if j.status in ACTIVE_JOB_STATUSES), None)
    return ledger, meeting, active or (jobs[0] if jobs else None)


async def recent_state(db, requester, event):
    result = await visible_result(db, requester.upn, event)
    if result:
        return {"action": "view", "meeting_id": str(result.id)}
    request = await db.scalar(select(RecordingProcessingRequest).where(
        RecordingProcessingRequest.requester_user_id == requester.id,
        RecordingProcessingRequest.occurrence_key == occurrence_key(event),
        RecordingProcessingRequest.status.in_(["pending", "approved"])
    ).order_by(RecordingProcessingRequest.created_at.desc()).limit(1))
    if request:
        if request.status == "pending":
            return {"action": "request_pending", "request_id": str(request.id)}
        _, meeting, job = await recording_state(db, request.drive_id, request.drive_item_id)
        return {"action": "processing", "processing_status": job.status if job else "unavailable",
                "request_id": str(request.id)}
    try:
        owner, drive, item = await discover(db, requester, event)
        ledger, meeting, job = await recording_state(db, drive, item["id"])
        if meeting and meeting.state in DONE:
            # Existing results require row-level view permission; no new transcription.
            return {"action": "unavailable", "reason": "Existing result requires meeting access"}
        if job and job.status in ACTIVE_JOB_STATUSES:
            return {"action": "processing", "processing_status": job.status}
        if ledger:
            return {"action": "unavailable", "reason": "Owner must manage the existing recording job"}
        return {"action": "process" if owner.id == requester.id else "request_processing"}
    except HTTPException as exc:
        no_match = exc.status_code == 404 or exc.detail == "Ambiguous recording match"
        return {"action": "no_recording" if no_match else "unavailable", "reason": exc.detail}


async def create_request(db, upn, event_id):
    requester = await user_by_upn(db, upn, lock=True)
    if not requester.is_subscribed:
        raise HTTPException(403, "Subscribe before requesting processing")
    event = await read_event(upn, event_id, recent=True)
    if await visible_result(db, upn, event):
        raise HTTPException(409, "Meeting already processed; use View")
    existing = await db.scalar(select(RecordingProcessingRequest.id).where(
        RecordingProcessingRequest.requester_user_id == requester.id,
        RecordingProcessingRequest.occurrence_key == occurrence_key(event),
        RecordingProcessingRequest.status.in_(["pending", "approved"])))
    if existing:
        raise HTTPException(409, "A processing request already exists")
    owner, drive, item = await discover(db, requester, event)
    if owner.id == requester.id:
        raise HTTPException(409, "Use Process for your own recording")
    item = await verify_item(drive, item, event)
    ledger, meeting, job = await recording_state(db, drive, item["id"])
    if ledger or meeting or job:
        raise HTTPException(409, "Recording already imported or queued")
    request = RecordingProcessingRequest(requester_user_id=requester.id, recording_owner_user_id=owner.id,
        event_id=event_id, occurrence_key=occurrence_key(event), event_snapshot=snapshot(event),
        drive_id=drive, drive_item_id=item["id"], status="pending")
    db.add(request)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "A pending processing request already exists") from exc
    return request


async def apply_calendar_access(db, meeting, event):
    """Use verified Calendar identity, never the file creator, for organizer rights."""
    from app.services.recording_enrichment import apply_calendar_event
    event = snapshot(event)
    event["attendees"] = [a for a in event.get("attendees", [])
                          if a.get("type") != "resource"
                          and (a.get("status") or {}).get("response") != "declined"]
    apply_calendar_event(meeting, event)
    metadata = dict(meeting.extracted_json or {})
    metadata["t5_calendar_event"] = snapshot(event)
    metadata["calendar_occurrence_key"] = occurrence_key(event)
    meeting.extracted_json = metadata
    participants = list(await db.scalars(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id)))
    for participant in participants:
        participant.is_organizer = participant.user_upn.lower() == organizer(event)
    registered = list(await db.scalars(select(RegisteredUser).where(RegisteredUser.upn.in_(people(event)))))
    existing = {p.user_upn.lower() for p in participants}
    for user in registered:
        if user.upn.lower() not in existing:
            db.add(MeetingParticipant(meeting_id=meeting.id, user_upn=user.upn,
                                     is_organizer=user.upn.lower() == organizer(event), access_type="participant"))


async def queue_verified(db, owner, drive, item, event):
    ledger, meeting, job = await recording_state(db, drive, item["id"])
    if job and job.owner_upn.lower() != owner.upn.lower():
        raise HTTPException(409, "Recording job owner identity conflict")
    bound = (meeting.extracted_json or {}).get("calendar_occurrence_key") if meeting else None
    if bound and bound != occurrence_key(event):
        raise HTTPException(409, "Recording is bound to another meeting")
    if meeting and meeting.state in DONE:
        return meeting, job  # No transcription or review metadata replacement.
    if not job or job.status not in ACTIVE_JOB_STATUSES:
        if ledger:
            raise HTTPException(409, "Owner must retry the existing recording job")
        if not await enqueue_recording_job(db, drive_item_id=item["id"], drive_id=drive,
                owner_upn=owner.upn, source="calendar_processing", etag=item.get("eTag"), commit=False):
            raise HTTPException(409, "Recording concurrently queued; refresh and retry approval")
        job = await db.scalar(select(RecordingJob).where(RecordingJob.drive_item_id == item["id"],
                                                       RecordingJob.status.in_(ACTIVE_JOB_STATUSES)))
    if not meeting:
        meeting = Meeting(drive_item_id=item["id"], title=event.get("subject"), organizer_upn=organizer(event))
        db.add(meeting)
        await db.flush()
    bound = (meeting.extracted_json or {}).get("calendar_occurrence_key")
    if bound and bound != occurrence_key(event):
        raise HTTPException(409, "Recording is bound to another meeting")
    await apply_calendar_access(db, meeting, event)
    return meeting, job


async def decide_request(db, upn, request_id, approved):
    owner = await user_by_upn(db, upn, lock=True)
    request = await db.scalar(select(RecordingProcessingRequest).where(
        RecordingProcessingRequest.id == request_id).with_for_update())
    if not request or request.recording_owner_user_id != owner.id:
        raise HTTPException(403, "Only the recording owner can decide this request")
    target = "approved" if approved else "denied"
    if request.status != "pending":
        if request.status == target:
            return request
        raise HTTPException(409, "Request already decided")
    if approved:
        if not owner.is_subscribed:
            raise HTTPException(403, "Recording owner is no longer subscribed")
        requester = await db.get(RegisteredUser, request.requester_user_id)
        if not requester or not requester.is_subscribed:
            raise HTTPException(403, "Requester is no longer subscribed")
        event = await read_event(requester.upn, request.event_id)
        if occurrence_key(event) != request.occurrence_key:
            raise HTTPException(409, "Meeting occurrence changed; request is stale")
        try:
            found = await scan_owner(owner, event, requester.upn)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, "Recording unavailable; approval not saved") from exc
        if len(found) != 1 or found[0][1] != request.drive_id or found[0][2]["id"] != request.drive_item_id:
            raise HTTPException(409, "Recording ownership or reliable match changed")
        item = await verify_item(request.drive_id, found[0][2], event)
        meeting, job = await queue_verified(db, owner, request.drive_id, item, event)
        # Existing completed results get only verified requester view access, no role escalation.
        if meeting.state in DONE:
            participant = await db.scalar(select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == meeting.id, MeetingParticipant.user_upn == requester.upn))
            if not participant:
                db.add(MeetingParticipant(meeting_id=meeting.id, user_upn=requester.upn,
                                         is_organizer=False, access_type="participant"))
        request.meeting_id, request.job_id = meeting.id, job.id if job else None
        request.event_snapshot = snapshot(event)
    request.status = target
    request.decided_by, request.decided_at = owner.id, datetime.now(timezone.utc)
    await db.commit()
    return request


async def process_own_event(db, upn, event_id):
    requester = await user_by_upn(db, upn, lock=True)
    if not requester.is_subscribed:
        raise HTTPException(403, "Subscribe before processing")
    event = await read_event(upn, event_id, recent=True)
    if await visible_result(db, upn, event):
        raise HTTPException(409, "Meeting already processed; use View")
    owner, drive, item = await discover(db, requester, event)
    if owner.id != requester.id:
        raise HTTPException(403, "Request the recording owner's approval")
    item = await verify_item(drive, item, event)
    meeting, job = await queue_verified(db, owner, drive, item, event)
    await db.commit()
    return {"ok": True, "meeting_id": str(meeting.id), "job_id": str(job.id) if job else None}


async def list_requests(db, user):
    return list(await db.scalars(select(RecordingProcessingRequest).where(or_(
        RecordingProcessingRequest.requester_user_id == user.id,
        RecordingProcessingRequest.recording_owner_user_id == user.id
    )).order_by(RecordingProcessingRequest.created_at.desc())))
