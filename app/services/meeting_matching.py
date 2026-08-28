"""Helpers for matching a OneDrive recording to its Outlook meeting."""

from __future__ import annotations

import re
from datetime import datetime, timezone
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
    title = re.sub(r"[-_ ]*Meeting Recording$", "", title, flags=re.I)
    title = re.sub(r"[-_]+", " ", title)
    return re.sub(r"\s+", " ", title).strip(" -_") or "Meeting recording"


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


def match_calendar_event(
    recording_name: str,
    recorded_at: datetime | None,
    events: list[dict],
) -> dict | None:
    """Return the most plausible event without guessing across unrelated dates."""
    recording_title = _normalise(clean_recording_title(recording_name))
    best: tuple[float, dict] | None = None
    for event in events:
        event_start = parse_graph_datetime(event.get("start"))
        event_title = _normalise(event.get("subject") or "")
        title_score = SequenceMatcher(None, recording_title, event_title).ratio() * 60
        time_score = 0.0
        if recorded_at and event_start:
            left = recorded_at.astimezone(timezone.utc)
            right = event_start.astimezone(timezone.utc)
            hours = abs((left - right).total_seconds()) / 3600
            if hours <= 3:
                time_score = 60
            elif hours <= 12:
                time_score = 45
            elif hours <= 30:
                time_score = 25
            else:
                time_score = -60
        if not event_start or recorded_at is None or hours > 30:
            continue
        score = title_score + time_score
        if best is None or score > best[0]:
            best = (score, event)
    return best[1] if best and best[0] >= 35 else None


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
