"""Shared meeting-access predicates."""

from collections.abc import Mapping


NO_VIEW_ACCESS_TYPES = frozenset({"request_view", "request_edit", "revoked"})


def has_view_access(participant: Mapping | object) -> bool:
    """Return whether a participant row grants meeting visibility."""
    access_type = (
        participant.get("access_type")
        if isinstance(participant, Mapping)
        else getattr(participant, "access_type", None)
    )
    return access_type not in NO_VIEW_ACCESS_TYPES
