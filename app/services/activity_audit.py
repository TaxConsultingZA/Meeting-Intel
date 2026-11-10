"""Content-free activity facts staged in the workflow transaction."""
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from .audit import add_audit_event


def add_activity(db, *, meeting_id, upn, action, target_upn=None, resource_id=None, outcome="succeeded", error_category=None, correlation_id=None, metadata=None):
    identity = uuid4()
    correlation_id = correlation_id or identity
    meeting_id = UUID(str(meeting_id))
    metadata = dict(metadata or {})
    if target_upn:
        metadata["subject_actor_id"] = str(uuid5(NAMESPACE_URL,
            f"meeting-intel:activity-actor:{target_upn.strip().lower()}"))
    if error_category:
        metadata["error_category"] = error_category
    return add_audit_event(db, event_type=action, outcome=outcome,
        actor_type="user", actor_id=str(uuid5(NAMESPACE_URL,
            f"meeting-intel:activity-actor:{upn.strip().lower()}")), actor_upn=upn,
        resource_type="action_item" if resource_id else "meeting",
        resource_id=UUID(str(resource_id)) if resource_id else meeting_id, meeting_id=meeting_id,
        correlation_id=correlation_id, event_key=f"{action}:{identity}", metadata=metadata)
