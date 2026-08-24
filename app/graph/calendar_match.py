"""Microsoft Graph calendar lookup used for recording/event matching."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.graph import client as graph_client


def _setting(*names: str) -> str:
    for name in names:
        value = getattr(graph_client.settings, name, None)
        if value:
            return str(value)
    return ""


async def _token() -> str:
    tenant = _setting("microsoft_tenant_id", "entra_tenant_id", "auth_microsoft_entra_id_tenant_id")
    client_id = _setting("microsoft_client_id", "entra_client_id", "auth_microsoft_entra_id_id")
    secret = _setting("microsoft_client_secret", "entra_client_secret", "auth_microsoft_entra_id_secret")
    if not tenant or not client_id or not secret:
        raise RuntimeError("Microsoft Graph application credentials are incomplete")
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def events_between(upn: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    token = await _token()
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
