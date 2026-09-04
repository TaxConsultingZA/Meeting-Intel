"""Safety checks for replacing an existing successful processing result."""
import hashlib
import json

from ..models import ProcessingState


MANUAL_REPROCESS_SOURCE = "manual_reprocess"


def is_meeting_organizer(meeting, upn: str) -> bool:
    normalized = upn.strip().lower()
    return (getattr(meeting, "organizer_upn", None) or "").strip().lower() == normalized or any(
        (participant.user_upn or "").strip().lower() == normalized
        and participant.is_organizer
        for participant in (getattr(meeting, "participants", None) or [])
    )


def is_clean_reprocess_candidate(meeting) -> bool:
    """Return true only when current fields prove the review draft is untouched."""
    if meeting.state != ProcessingState.awaiting_review:
        return False
    extracted = getattr(meeting, "extracted_json", None)
    if not isinstance(extracted, dict):
        return False
    raw_transcript = extracted.get("raw_transcript")
    if not isinstance(raw_transcript, str) or raw_transcript != getattr(meeting, "transcript", None):
        return False
    if extracted.get("speaker_mappings"):
        return False
    if (
        getattr(meeting, "approved_by", None)
        or getattr(meeting, "approved_at", None)
        or getattr(meeting, "approved_recipients", None)
        or getattr(meeting, "email_delivery_status", None) in {"sending", "sent"}
    ):
        return False
    return all(
        not getattr(item, "edited_by", None) and not getattr(item, "approved", False)
        for item in (getattr(meeting, "action_items", None) or [])
    )


def result_fingerprint(meeting) -> str:
    """Fingerprint every review/output field that a reprocess must not race."""
    state = meeting.state.value if hasattr(meeting.state, "value") else str(meeting.state)
    actions = []
    for item in (getattr(meeting, "action_items", None) or []):
        actions.append({
            "id": str(getattr(item, "id", "")),
            "task": getattr(item, "task", None),
            "owner": getattr(item, "owner", None),
            "deadline_text": getattr(item, "deadline_text", None),
            "deadline_iso": getattr(item, "deadline_iso", None),
            "confidence": str(getattr(item, "confidence", None)),
            "source_quote": getattr(item, "source_quote", None),
            "approved": getattr(item, "approved", False),
            "edited_by": getattr(item, "edited_by", None),
            "raw": getattr(item, "raw", None),
        })
    payload = {
        "state": state,
        "transcript": meeting.transcript,
        "summary": meeting.summary,
        "extracted_json": meeting.extracted_json,
        "approved_recipients": getattr(meeting, "approved_recipients", None),
        "approved_by": getattr(meeting, "approved_by", None),
        "approved_at": getattr(meeting, "approved_at", None),
        "email_delivery_status": getattr(meeting, "email_delivery_status", None),
        "email_delivery_fingerprint": getattr(meeting, "email_delivery_fingerprint", None),
        "actions": sorted(actions, key=lambda action: action["id"]),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
