"""Independent, server-written action confirmation; never approves notes."""
from datetime import date
import re

from sqlalchemy import or_

from ..models import ActionItem, Meeting, ProcessingState

INSIGHT_CONFIRMATION_ORIGIN = "mock_insight_human_confirmed"
APPROVED_NOTE_STATES = (ProcessingState.approved, ProcessingState.sent)


def confirmed_deadline_iso(value: str | None) -> str | None:
    """Copy an explicit reviewed calendar date; never resolve relative wording."""
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def is_confirmed_insight(item: ActionItem) -> bool:
    raw = getattr(item, "raw", None)
    return isinstance(raw, dict) and raw.get("origin") == INSIGHT_CONFIRMATION_ORIGIN


def task_is_reviewed(meeting: Meeting, item: ActionItem) -> bool:
    return bool(item.approved and (is_confirmed_insight(item) or meeting.state in APPROVED_NOTE_STATES))


def reviewed_task_clause():
    # Matches the human-confirmation producer in meeting-insights-foundation.
    # Neither a candidate status nor a name/date inferred by AI is confirmation.
    return or_(Meeting.state.in_(APPROVED_NOTE_STATES),
               ActionItem.raw["origin"].as_string() == INSIGHT_CONFIRMATION_ORIGIN)
