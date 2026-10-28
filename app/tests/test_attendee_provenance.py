from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.reviews import _to_out, _with_recording_display
from app.models import ProcessingState
from app.tests.test_cross_user_recordings import ctx as ctx  # noqa: PLC0414

FILE = "01LIX265JFMJPO3YO52BELGAXDCTWU7SPI"
RECORD = "cf0acc35-d1cb-4847-b099-8620e971ebdb"

@pytest.mark.parametrize("status,event_id,expected", [
    ("needs_review", None, False), ("unmatched", None, False),
    ("independent", None, False), ("linked", "trust-event", True),
    ("linked", "different-event", False),
])
async def test_exact_record_identity_controls_people_without_mutation(status, event_id, expected):
    meeting = SimpleNamespace(id=RECORD, drive_item_id=FILE, title="Trust",
        state=ProcessingState.awaiting_review, summary=None, transcript="[Speaker A] Hello",
        organizer_upn="trust-organizer@example.test", error=None, recorded_at=None,
        attendees_raw=[{"emailAddress":{"address":"trust-guest@example.test", "name":"Trust Guest"}}],
        extracted_json={"outlook_event_id":"trust-event", "attendees":["Trust Guest"],
            "speaker_candidates":[{"email":"trust-guest@example.test"}],
            "speaker_mappings":{"Speaker A":"saved@example.test"},
            "transcript_segments":[{"speaker":"Speaker A", "text":"Hello"}]},
        participants=[], action_items=[], approved_recipients=[])
    before = deepcopy(meeting.__dict__)
    ledger = SimpleNamespace(drive_item_id=FILE, drive_id="exact-drive", filename="Test.mp4",
        identity_json={"status":status,"event":{"id":event_id} if event_id else None})
    db = SimpleNamespace(scalars=AsyncMock(return_value=[ledger]))
    out = (await _with_recording_display(db, [meeting], [_to_out(meeting, is_admin=True)]))[0]
    assert bool(out.calendar_participants) is expected
    assert bool(out.organizer_upn) is expected
    assert bool(out.speaker_candidates) is expected
    assert out.speaker_mappings == {"Speaker A":"saved@example.test"}
    assert out.speaker_sample_labels == ["Speaker A"]
    assert out.transcript == meeting.transcript
    if not expected:
        assert out.email_recipients == []
        assert "Trust Guest" not in str(out.extracted_json)
    assert meeting.__dict__ == before
    assert "drive_item_id IN" in str(db.scalars.call_args.args[0])


async def test_old_trust_fields_do_not_leak_through_exact_sqlite_ledger(ctx):
    from app.models import Meeting, ProcessedItem
    row = ProcessedItem(drive_item_id=FILE, drive_id="exact-drive", filename="Test.mp4",
        source="manual", identity_json={"status":"needs_review", "event":None})
    meeting = Meeting(drive_item_id=FILE, title="Trust", state=ProcessingState.awaiting_review,
        organizer_upn="trust@example.test", attendees_raw=["trust-guest@example.test"],
        extracted_json={"outlook_event_id":"trust-event", "speaker_candidates":["trust@example.test"]})
    ctx.session.add_all([row, meeting]);ctx.session.commit()
    meeting.participants = []; meeting.action_items = []
    out = (await _with_recording_display(ctx.db, [meeting], [_to_out(meeting)]))[0]
    assert out.calendar_participants == [] and out.speaker_candidates == []
    assert out.organizer_upn is None
    ctx.session.expire_all()
    assert ctx.session.get(Meeting, meeting.id).organizer_upn == "trust@example.test"
