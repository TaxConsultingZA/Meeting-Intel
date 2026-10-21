"""Microsoft Graph calendar lookup used for recording/event matching."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.graph.client import get_calendar_window


async def events_between(upn: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    # Reuse the configured Graph endpoint and validated pagination. A match may
    # be on a later page even in a short window (e.g. a busy/shared calendar).
    return await get_calendar_window(upn, start, end)
