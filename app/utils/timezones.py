"""Graph dateTimeTimeZone -> an unambiguous UTC instant (never host local time)."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WINDOWS_ZONES = {
    "UTC": "UTC", "Coordinated Universal Time": "UTC",
    "South Africa Standard Time": "Africa/Johannesburg",
    "China Standard Time": "Asia/Shanghai",
    "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin",
    "Eastern Standard Time": "America/New_York", "Pacific Standard Time": "America/Los_Angeles",
    "India Standard Time": "Asia/Kolkata",
}


def parse_graph_datetime(value, default_zone="UTC") -> datetime | None:
    zone = default_zone
    if isinstance(value, dict):
        zone = value.get("timeZone") or default_zone
        value = value.get("dateTime")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(WINDOWS_ZONES.get(zone, zone)))
        return parsed.astimezone(timezone.utc)
    except (ValueError, ZoneInfoNotFoundError):
        # Unknown zones are not silently interpreted as UTC.
        return None


def utc_iso(value):
    parsed = parse_graph_datetime(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None
