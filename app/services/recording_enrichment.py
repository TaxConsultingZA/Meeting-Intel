"""Attach Outlook date and participants to an imported OneDrive recording."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.graph import client as graph
from app.graph.calendar_match import events_between
from app.services.meeting_matching import event_people, match_calendar_event, recording_datetime
from app.utils.timezones import parse_graph_datetime


logger = logging.getLogger(__name__)


async def enrich_recording_from_outlook(
    meeting: Any,
    drive_id: str,
    drive_item_id: str,
    candidate_upns: list[str] | None = None,
) -> None:
    item = await graph.get_drive_item(drive_id, drive_item_id)
    recorded_at = recording_datetime(item.get("name", ""), item)
    if recorded_at and not meeting.recorded_at:
        meeting.recorded_at = recorded_at

    organizer = (meeting.organizer_upn or "").strip().lower()
    if not organizer or not recorded_at:
        return

    window_start = recorded_at - timedelta(days=2)
    window_end = recorded_at + timedelta(days=2)
    events = await events_between(organizer, window_start, window_end)
    event = match_calendar_event(item.get("name", ""), recorded_at, events)
    if not event:
        seen = {organizer}
        for upn in candidate_upns or []:
            upn = (upn or "").strip().lower()
            if not upn or upn in seen:
                continue
            seen.add(upn)
            try:
                events.extend(await events_between(upn, window_start, window_end))
            except Exception:
                logger.warning("Could not read fallback Outlook calendar for recording match")
        event = match_calendar_event(item.get("name", ""), recorded_at, events)
    if not event:
        logger.info("No Outlook event matched OneDrive recording %s", drive_item_id)
        return

    emails, names = event_people(event)
    people = [{"email": email, "name": names.get(email, email)} for email in emails]
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for person in people:
        email = (person.get("email") or "").strip().lower()
        name = (person.get("name") or "").strip()
        key = email or name.lower()
        if key and key not in seen:
            seen.add(key)
            candidates.append({"name": name or email, "email": email})

    subject = (event.get("subject") or "").strip()
    event_start = parse_graph_datetime(event.get("start"))
    if subject:
        meeting.title = subject
    if event_start:
        meeting.recorded_at = event_start
    meeting.attendees_raw = [
        {"emailAddress": {"name": person["name"], "address": person["email"]}}
        for person in people
        if person.get("email")
    ]

    metadata = dict(meeting.extracted_json or {})
    metadata.update(
        {
            "outlook_event_id": event.get("id"),
            "meeting_time": meeting.recorded_at.isoformat() if meeting.recorded_at else None,
            "attendees": [person["name"] for person in people],
            "meeting_timezone": (event.get("start") or {}).get("timeZone"),
            "speaker_candidates": candidates,
        }
    )
    meeting.extracted_json = metadata
