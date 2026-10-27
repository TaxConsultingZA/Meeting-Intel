"""Regression cases from GET-only file/calendar reconciliation, without tenant IDs."""
from datetime import datetime

import pytest

from app.services.meeting_matching import recording_datetime
from app.services.recording_update import strong_match


OWNER = "owner@example.test"
CASES = [
    ("Test-20260901_164158-会议记录.mp4", "2026-09-01T08:41:58Z", "Test",
     "2026-09-01T08:30:00Z", "2026-09-01T09:00:00Z"),
    ("与 Wei Jiuyang 的会议-20261022_145031-会议记录.mp4", "2026-10-22T06:50:32Z",
     "与 Wei Jiuyang 的会议", "2026-10-22T06:50:00Z", "2026-10-22T06:51:00Z"),
]


def event(title, start, end, key):
    return {"id": key, "iCalUId": key, "subject": title, "isCancelled": False,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
            "organizer": {"emailAddress": {"address": OWNER}}, "attendees": []}


@pytest.mark.parametrize("filename,instant,title,start,end", CASES)
def test_graph_instant_is_not_shifted_to_match_filename_wall_clock(filename, instant, title, start, end):
    metadata = {"createdDateTime": instant, "fileSystemInfo": {"createdDateTime": instant}}
    parsed = recording_datetime(filename, metadata)
    assert parsed == datetime.fromisoformat(instant)
    # Synthetic stable IDs demonstrate that an actual matching event would be accepted.
    candidate = event(title, start, end, "verified-occurrence")
    assert strong_match(filename, parsed, [candidate], OWNER) is candidate
    assert strong_match(filename, parsed, [candidate], "other@example.test") is None


def test_september_test_never_links_trust_or_next_days_test():
    filename, instant, _, start, end = CASES[0]
    candidates = [event("Trust IT3(t) Reporting – Practical Classroom Session", start, end, "trust"),
                  event("test", "2026-09-02T08:15:00Z", "2026-09-02T08:45:00Z", "next-day")]
    assert strong_match(filename, datetime.fromisoformat(instant), candidates, OWNER) is None


def test_october_recording_does_not_link_overlapping_different_title():
    filename, instant, _, _, _ = CASES[1]
    unrelated = event("test 10.22", "2026-10-22T06:30:00Z", "2026-10-22T07:00:00Z", "other-meeting")
    assert strong_match(filename, datetime.fromisoformat(instant), [unrelated], OWNER) is None


@pytest.mark.parametrize("filename,instant,title,start,end", CASES)
def test_cancelled_or_ambiguous_occurrences_remain_unmatched(filename, instant, title, start, end):
    candidate = event(title, start, end, "first")
    parsed = datetime.fromisoformat(instant)
    assert strong_match(filename, parsed, [dict(candidate, isCancelled=True)], OWNER) is None
    duplicate = event(title, start, end, "second")
    for events in ([candidate, duplicate], [duplicate, candidate]):
        assert strong_match(filename, parsed, events, OWNER) is None

@pytest.mark.parametrize("metadata",[
 {"lastModifiedDateTime":"2026-10-22T06:52:36Z"},
 {"createdDateTime":"2026-10-22T14:50:32"},
 {"first_seen_at":"2026-10-26T08:19:19Z"},
])
def test_missing_real_creation_instant_never_uses_modified_discovery_or_filename_time(metadata):
 assert recording_datetime(CASES[1][0],metadata) is None
