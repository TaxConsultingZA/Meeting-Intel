"""Helpers for matching a OneDrive recording to its Outlook meeting."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from app.utils.timezones import parse_graph_datetime


_STAMP = re.compile(r"(?P<date>20\d{6})[_-](?P<time>\d{6})")


def recording_datetime(name: str, metadata: dict | None = None) -> datetime | None:
    # Filename stamps have no reliable zone. Prefer Graph's offset-bearing
    # metadata rather than guessing that the recorder's local clock was UTC.
    metadata = metadata or {}
    file_system = metadata.get("fileSystemInfo") or {}
    return parse_graph_datetime(
        file_system.get("createdDateTime")
        or file_system.get("lastModifiedDateTime")
        or metadata.get("createdDateTime")
        or metadata.get("lastModifiedDateTime")
    )


def clean_recording_title(name: str) -> str:
    title = Path(name or "Recording").stem
    title = _STAMP.sub("", title)
    title = re.sub(r"[-_ ]*(?:Meeting Recording|会议记录|會議錄製)$", "", title, flags=re.I)
    title = re.sub(r"[-_]+", " ", title)
    return re.sub(r"\s+", " ", title).strip(" -_") or "Meeting recording"


def _normalise(value: str) -> str:
    value = re.sub(r"^(?:已取消|Canceled|Cancelled)\s*:\s*", "", value or "", flags=re.I)
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def match_calendar_event(
    recording_name: str,
    recorded_at: datetime | None,
    events: list[dict],
) -> dict | None:
    """Return a nearby, title-compatible event or decline to guess."""
    recording_title = _normalise(clean_recording_title(recording_name))
    candidates: list[tuple[float, dict]] = []
    for event in events:
        event_start = parse_graph_datetime(event.get("start"))
        event_end = parse_graph_datetime(event.get("end"))
        event_title = _normalise(event.get("subject") or "")
        title_similarity = SequenceMatcher(None, recording_title, event_title).ratio()
        if not recording_title or not event_title or title_similarity < 0.5 or not event_start or recorded_at is None:
            continue

        instant = recorded_at.astimezone(timezone.utc)
        start = event_start.astimezone(timezone.utc)
        end = (event_end or event_start).astimezone(timezone.utc)
        if end < start:
            end = start
        if instant < start:
            distance = start - instant
        elif instant > end:
            distance = instant - end
        else:
            distance = timedelta(0)
        if distance > timedelta(hours=3):
            continue

        score = title_similarity * 100 - distance.total_seconds() / 3600
        candidates.append((score, event))
    if not candidates:
        return None
    best_score, best = max(candidates, key=lambda candidate: candidate[0])
    for score, event in candidates:
        # Upload/creation time is not meeting identity. Across the entire
        # three-hour window, time alone cannot distinguish equal-title events.
        if event is best or best_score - score > 3:
            continue
        same_occurrence = bool(
            event.get("iCalUId") and event.get("iCalUId") == best.get("iCalUId")
            and parse_graph_datetime(event.get("start")) == parse_graph_datetime(best.get("start"))
            and parse_graph_datetime(event.get("end")) == parse_graph_datetime(best.get("end"))
            and event.get("organizer") == best.get("organizer")
        )
        if not same_occurrence:
            return None
    return best


def event_people(event: dict | None) -> tuple[list[str], dict[str, str]]:
    emails: list[str] = []
    names: dict[str, str] = {}
    if not event:
        return emails, names
    entries = list(event.get("attendees") or [])
    organiser = event.get("organizer") or event.get("organiser")
    if organiser:
        entries.append(organiser)
    for entry in entries:
        email_address = (entry or {}).get("emailAddress") or {}
        address = (email_address.get("address") or "").strip().lower()
        if not address:
            continue
        if address not in emails:
            emails.append(address)
        display_name = (email_address.get("name") or "").strip()
        if display_name:
            names[address] = display_name
    return emails, names
