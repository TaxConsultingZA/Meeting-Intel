"""Bounded audit reads; cursor contents are untrusted, never authorization."""
import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import load_only

from ..models import AuditEvent
from ..schemas import AuditEventOut, AuditEventsPageOut


_TOKEN_VALUES = {
    "source": {"manual", "manual_retry", "manual_reprocess", "webhook", "calendar_processing", "reconcile"},
    "previous_state": {"pending", "processing", "failed", "cancelled", "completed"},
    "new_state": {"pending", "processing", "failed", "cancelled", "completed"},
    "error_category": {"processing_error", "interrupted", "attempts_exhausted", "reprocess_conflict"},
    "reason": {"lease_expired", "existing_result_preserved"},
}


def safe_metadata(value):
    """Only typed counters, IDs, and reviewed constants may reach the reader."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, allowed in _TOKEN_VALUES.items():
        item = value.get(key)
        if isinstance(item, str) and item in allowed:
            result[key] = item
    for key in ("attempt", "recipient_count"):
        item = value.get(key)
        if type(item) is int and 0 <= item <= 2**31 - 1:
            result[key] = item
    if type(value.get("retry_scheduled")) is bool:
        result["retry_scheduled"] = value["retry_scheduled"]
    try:
        if isinstance(value.get("parent_job_id"), str):
            result["parent_job_id"] = str(UUID(value["parent_job_id"]))
    except ValueError:
        pass
    return result


def _aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Dates must include a timezone")
    return value.astimezone(timezone.utc)


def _encode(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode(value):
    try:
        if len(value) > 2048 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError()
        result = json.loads(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
        if not isinstance(result, dict) or set(result) != {"v", "start", "end", "time", "id", "filters"} or result["v"] != 1:
            raise ValueError()
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid audit cursor") from exc


async def query_audit_events(db, *, limit=50, cursor=None, start=None, end=None,
                             event_type=None, outcome=None, actor_type=None,
                             actor_id=None, actor_upn=None):
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")
    if actor_upn is not None:
        actor_upn = actor_upn.strip().lower()
    filters = {"event_type": event_type, "outcome": outcome, "actor_type": actor_type,
               "actor_id": actor_id, "actor_upn": actor_upn}
    fingerprint = hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()
    boundary = None
    if cursor:
        decoded = _decode(cursor)
        try:
            cursor_start = _aware(datetime.fromisoformat(decoded["start"]))
            cursor_end = _aware(datetime.fromisoformat(decoded["end"]))
            boundary = (_aware(datetime.fromisoformat(decoded["time"])), UUID(decoded["id"]))
            if decoded["filters"] != fingerprint:
                raise ValueError()
            if start is not None and _aware(start) != cursor_start:
                raise ValueError()
            if end is not None and _aware(end) != cursor_end:
                raise ValueError()
            start, end = cursor_start, cursor_end
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid audit cursor or changed filters") from exc
    end = _aware(end) if end is not None else datetime.now(timezone.utc)
    start = _aware(start) if start is not None else end - timedelta(days=7)
    if start >= end or end - start > timedelta(days=90):
        raise ValueError("Date range must be positive and at most 90 days")
    if boundary is not None and not start <= boundary[0] < end:
        raise ValueError("Invalid audit cursor")
    statement = select(AuditEvent).options(load_only(
        AuditEvent.id, AuditEvent.occurred_at, AuditEvent.event_type, AuditEvent.outcome,
        AuditEvent.actor_type, AuditEvent.actor_id, AuditEvent.actor_upn,
        AuditEvent.resource_type, AuditEvent.resource_id, AuditEvent.meeting_id,
        AuditEvent.job_id, AuditEvent.correlation_id, AuditEvent.event_metadata,
    )).where(AuditEvent.occurred_at >= start, AuditEvent.occurred_at < end)
    for name, value in filters.items():
        if value is not None:
            statement = statement.where(getattr(AuditEvent, name) == value)
    if boundary is not None:
        statement = statement.where(tuple_(AuditEvent.occurred_at, AuditEvent.id) < boundary)
    statement = statement.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
    rows = list((await db.scalars(statement)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = _encode({"v": 1, "start": start.isoformat(), "end": end.isoformat(),
                               "time": _aware(last.occurred_at).isoformat(), "id": str(last.id),
                               "filters": fingerprint})
    items = [AuditEventOut(
        id=row.id, occurred_at=_aware(row.occurred_at), event_type=row.event_type,
        outcome=row.outcome, actor_type=row.actor_type, actor_id=row.actor_id,
        actor_upn=row.actor_upn, resource_type=row.resource_type, resource_id=row.resource_id,
        meeting_id=row.meeting_id, job_id=row.job_id, correlation_id=row.correlation_id,
        metadata=safe_metadata(row.event_metadata),
    ) for row in rows]
    return AuditEventsPageOut(items=items, next_cursor=next_cursor, has_more=has_more,
                              window_start=start, window_end=end)
