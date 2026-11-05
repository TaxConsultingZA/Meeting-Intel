"""Read-only date provenance for meeting cards; never infer from job clocks or titles."""
from app.utils.timezones import parse_graph_datetime


def _result(value, source, reason, raw_time=None, event_id=None):
    return dict(value=value, source=source, date_source=source, reason=reason, raw_time=raw_time, event_id=event_id)


def card_date(recorded_at, metadata, current_identity=None):
    metadata = metadata if isinstance(metadata, dict) else {}
    identity = metadata.get("recording_identity")
    identity = identity if isinstance(identity, dict) else {}
    event = identity.get("event")
    event = event if isinstance(event, dict) else {}
    verified = metadata.get("t5_calendar_event")
    verified = verified if isinstance(verified, dict) else {}
    if isinstance(current_identity, dict) and current_identity:
        # Current exact-drive-item ledger supersedes historical extraction snapshots.
        identity = current_identity
        event = identity.get("event")
        event = event if isinstance(event, dict) else {}
        verified = {}
        metadata = {}
        recorded_at = None
    candidates = []
    if verified.get("id") and not verified.get("isCancelled"):
        candidates.append((verified.get("start"), verified["id"]))
    if (identity.get("status") == "linked"
            and (identity.get("evidence") == "unique_exact_title_time_owner_stable_id"
                 or bool(identity.get("decided_by") and identity.get("decided_at")))
            and event.get("id") and not event.get("isCancelled")):
        candidates.append((event.get("start"), event["id"]))
    if metadata.get("outlook_event_id"):
        candidates.append((recorded_at.isoformat() if recorded_at else None, metadata["outlook_event_id"]))
    for value, event_id in candidates:
        instant = parse_graph_datetime(value)
        if instant:
            return _result(instant.isoformat(), "meeting", None, value, event_id)
    # recorded_at historically stores either calendar start or recording metadata.
    # Without calendar provenance it must never be labelled meeting start.
    for value in [identity.get("recorded_at"), recorded_at.isoformat() if recorded_at else None]:
        instant = parse_graph_datetime(value)
        if instant:
            return _result(instant.isoformat(), "recording", "No verified meeting start; recording metadata time only.", value)
    return _result(None, "unavailable", "No verified calendar start or stored recording timestamp; filenames, extracted text and job creation times are not date evidence.")
