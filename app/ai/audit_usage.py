"""Task-local handoff of provider-returned counters, without content or transport."""
from contextvars import ContextVar

reported_usage = ContextVar("audit_reported_usage", default=None)


def capture_usage(value):
    target = reported_usage.get()
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if target is not None and isinstance(value, dict) and all(type(value.get(k)) is int and 0 <= value[k] <= 2**31 - 1 for k in keys):
        if value["total_tokens"] == value["prompt_tokens"] + value["completion_tokens"]:
            target.update({k: value[k] for k in keys})
