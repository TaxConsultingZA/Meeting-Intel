"""Email approval events staged in the workflow's own transactions."""
from uuid import UUID, NAMESPACE_URL, uuid5

import httpx

from .audit import add_audit_event


def submission_failure(exc: BaseException) -> tuple[str, str]:
    """Only known pre-submission failures and explicit rejections are retryable."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return "failed", "connection_unavailable"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if 400 <= status < 500 and status != 408:
            return "failed", "provider_rejected"
    # Read/write timeouts, cancellation, 5xx, and unclassified exceptions may
    # occur after acceptance. Never infer non-delivery from their messages.
    return "unknown", "submission_uncertain"


def add_email_event(db, *, meeting_id, attempt, fingerprint, recipient_count,
                    event_type, outcome, actor=None, error_category=None):
    meeting_id = UUID(str(meeting_id))
    correlation_id = uuid5(NAMESPACE_URL,
        f"meeting-intel:email-approval:{meeting_id}:{attempt}:{fingerprint}")
    metadata = {"attempt": attempt, "fingerprint": fingerprint,
                "recipient_count": recipient_count, "email_category": "meeting_notes"}
    if error_category is not None:
        metadata["error_category"] = error_category
    identity = ({"actor_type": "user", **actor} if actor is not None else
                {"actor_type": "system", "actor_id": "email_sender"})
    return add_audit_event(db, event_type=event_type, outcome=outcome,
        **identity, resource_type="meeting", resource_id=meeting_id,
        meeting_id=meeting_id, correlation_id=correlation_id,
        event_key=f"{event_type}:{correlation_id}:{outcome}", metadata=metadata)
