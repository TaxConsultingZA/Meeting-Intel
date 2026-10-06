"""Stage audit events in a caller-owned transaction; no workflow integration."""
import json
import re
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditEvent


_OUTCOMES = frozenset({"requested", "succeeded", "failed", "unknown"})
_METADATA_KEYS = frozenset({
    "source", "parent_job_id", "attempt", "retry_scheduled", "previous_state",
    "new_state", "email_category", "recipient_count", "fingerprint",
    "error_category", "drive_id", "drive_item_id", "reason",
})


def _string(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a non-empty string of at most {limit} characters")
    return value


def add_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    outcome: str,
    actor_type: str,
    actor_id: str,
    resource_type: str,
    resource_id: UUID,
    correlation_id: UUID,
    event_key: str,
    actor_upn: str | None = None,
    actor_entra_oid: str | None = None,
    meeting_id: UUID | None = None,
    job_id: UUID | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    """Validate and add an event without flushing, committing, or querying.

    Callers own persistence and rollback. Duplicate event keys are rejected by
    the database at flush/commit; this function does not silently deduplicate.
    Metadata must contain only sanitized context, never content or credentials.
    """
    _string("event_type", event_type, 64)
    if not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", event_type):
        raise ValueError("event_type must use resource.action naming")
    if outcome not in _OUTCOMES:
        raise ValueError("Unsupported audit outcome")
    if actor_type not in {"user", "system"}:
        raise ValueError("Unsupported actor type")
    _string("actor_id", actor_id, 64)
    if actor_type == "user":
        UUID(actor_id)
        if actor_upn is None:
            raise ValueError("User actors require a UPN snapshot")
    if actor_upn is not None:
        actor_upn = _string("actor_upn", actor_upn, 255).strip().lower()
    if actor_entra_oid is not None:
        _string("actor_entra_oid", actor_entra_oid, 64)
    _string("resource_type", resource_type, 32)
    _string("event_key", event_key, 255)
    for name, value in (("resource_id", resource_id), ("correlation_id", correlation_id),
                        ("meeting_id", meeting_id), ("job_id", job_id)):
        if value is None and name in {"meeting_id", "job_id"}:
            continue
        if not isinstance(value, UUID):
            raise ValueError(f"{name} must be a UUID")
    context = {} if metadata is None else metadata
    if not isinstance(context, dict) or context.keys() - _METADATA_KEYS:
        raise ValueError("Unsupported audit metadata keys")
    if any(value is not None and type(value) not in {str, int, bool} for value in context.values()):
        raise ValueError("Audit metadata values must be strings, integers, booleans, or null")
    encoded = json.dumps(context, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 4096:
        raise ValueError("Audit metadata exceeds 4096 bytes")
    event = AuditEvent(
        id=uuid4(), event_type=event_type, outcome=outcome,
        actor_type=actor_type, actor_id=actor_id, actor_upn=actor_upn,
        actor_entra_oid=actor_entra_oid, resource_type=resource_type,
        resource_id=resource_id, meeting_id=meeting_id, job_id=job_id,
        correlation_id=correlation_id, event_key=event_key,
        event_metadata=json.loads(encoded),
    )
    db.add(event)
    return event
