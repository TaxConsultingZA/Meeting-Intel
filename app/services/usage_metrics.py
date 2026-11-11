"""Read-only completed-action usage metric helpers."""
from datetime import date


def validate_date_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError("The end date must not be before the start date.")
    if (end - start).days > 3660:
        raise ValueError("The date range is too large.")
