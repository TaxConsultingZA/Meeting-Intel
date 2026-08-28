"""Canonical identity helpers shared by ingestion and authorization code."""


def normalize_upn(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned if "@" in cleaned else None


def normalize_upns(values) -> list[str]:
    def identity_value(value):
        if not isinstance(value, dict):
            return value
        email_address = value.get("emailAddress") or {}
        return (
            email_address.get("address")
            or value.get("email")
            or value.get("userPrincipalName")
        )

    return list(dict.fromkeys(
        upn
        for value in (values or [])
        if (upn := normalize_upn(identity_value(value)))
    ))
