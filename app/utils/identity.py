"""Canonical identity helpers shared by ingestion and authorization code."""


def normalize_upn(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned if "@" in cleaned else None


def normalize_upns(values) -> list[str]:
    return list(dict.fromkeys(
        upn for value in (values or []) if (upn := normalize_upn(value))
    ))
