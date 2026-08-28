"""Microsoft Graph calendar lookup used for recording/event matching."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.graph.auth import get_token


async def events_between(upn: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    token = get_token()
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(
            f"https://graph.microsoft.com/v1.0/users/{quote(upn)}/calendarView",
            params={
                "startDateTime": start.isoformat().replace("+00:00", "Z"),
                "endDateTime": end.isoformat().replace("+00:00", "Z"),
                "$select": "id,subject,start,end,organizer,attendees,isOnlineMeeting,onlineMeetingProvider",
                "$orderby": "start/dateTime",
                "$top": "100",
            },
            headers={"Authorization": f"Bearer {token}", "Prefer": 'outlook.timezone="UTC"'},
        )
        response.raise_for_status()
        return response.json().get("value", [])
