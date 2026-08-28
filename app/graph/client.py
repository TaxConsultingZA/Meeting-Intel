import httpx
from datetime import datetime, timedelta, timezone
from .auth import get_token
from ..config import get_settings

settings = get_settings()


class ProfilePhotoNotFound(Exception):
    """The user does not have a Microsoft profile photo."""


def _mock_enabled() -> bool:
    """Return True only for the explicitly selected, fully local demo backend."""
    return settings.graph_impl == "mock"


def _headers() -> dict:
    """Build the Authorization header required by every Microsoft Graph request."""
    return {"Authorization": f"Bearer {get_token()}"}


async def list_domain_users() -> list[dict]:
    """Return all users whose mail is in the allowed domain.
    endswith filters require ConsistencyLevel: eventual + $count=true."""
    if _mock_enabled():
        return [{
            "id": "mock-user-demo",
            "mail": "demo.user@taxconsulting.co.za",
            "displayName": "Demo User",
        }]

    url = (
        f"{settings.graph_base}/users"
        f"?$filter=endswith(mail,'@{settings.allowed_domain}')"
        f"&$select=id,mail,displayName&$top=999&$count=true"
    )
    eventual_headers = {**_headers(), "ConsistencyLevel": "eventual"}
    users: list[dict] = []
    async with httpx.AsyncClient(timeout=60) as c:
        while url:
            r = await c.get(url, headers=eventual_headers)
            r.raise_for_status()
            data = r.json()
            users.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
    return users


async def get_user_drive_id(user_upn: str) -> str:
    """Return the OneDrive drive-id for a given user UPN."""
    if _mock_enabled():
        # Keep each local demo user's fake OneDrive independent.  Reusing one
        # drive/item id made a recording imported by one tester appear already
        # processed for every later tester.
        return f"mock-drive::{user_upn.lower()}"

    url = f"{settings.graph_base}/users/{user_upn}/drive"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=_headers())
        r.raise_for_status()
        return r.json()["id"]


async def get_user_photo(user_upn: str) -> tuple[bytes, str]:
    """Fetch a user's Microsoft 365 profile photo using app permissions."""
    if _mock_enabled():
        raise ProfilePhotoNotFound
    url = f"{settings.graph_base}/users/{user_upn}/photo/$value"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=_headers())
        if r.status_code == 404:
            raise ProfilePhotoNotFound
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "image/jpeg")


async def list_recordings_folder(drive_id: str) -> list[dict]:
    """List mp4 files in the Recordings folder of the given drive.
    Returns [] if the folder doesn't exist yet (new user with no recordings)."""
    if _mock_enabled():
        return [{
            "id": f"{drive_id}::recording-past-untranscribed",
            "name": "Past Client Update - Untranscribed.mp4",
            "size": 9_437_184,
            "createdDateTime": "2026-07-15T09:30:00Z",
            "eTag": '"mock-etag-past-1"',
        }]

    url = f"{settings.graph_base}/drives/{drive_id}/root:/Recordings:/children"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=_headers())
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return [i for i in r.json().get("value", []) if i.get("name", "").endswith(".mp4")]


async def get_drive_item(drive_id: str, item_id: str) -> dict:
    """Fetch a single OneDrive item's metadata (name, size, createdBy, etc.)."""
    if _mock_enabled():
        owner_upn = drive_id.removeprefix("mock-drive::")
        if not owner_upn or owner_upn == drive_id:
            owner_upn = "demo.user@taxconsulting.co.za"
        return {
            "id": item_id,
            "name": "Past Client Update - Untranscribed.mp4",
            "size": 9_437_184,
            "createdDateTime": "2026-07-15T09:30:00Z",
            "createdBy": {"user": {
                "displayName": owner_upn.split("@", 1)[0].replace(".", " ").title(),
                "userPrincipalName": owner_upn,
                "email": owner_upn,
            }},
        }

    url = f"{settings.graph_base}/drives/{drive_id}/items/{item_id}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=_headers())
        r.raise_for_status()
        return r.json()


async def download_drive_item(drive_id: str, item_id: str, dest_path: str) -> str:
    """Stream the recording to disk (don't load a 2h video into memory)."""
    if _mock_enabled():
        # The mock transcriber does not inspect media bytes. A small local marker
        # file proves the download step ran without touching OneDrive.
        with open(dest_path, "wb") as f:
            f.write(b"MEETING_INTEL_LOCAL_MOCK_RECORDING")
        return dest_path

    url = f"{settings.graph_base}/drives/{drive_id}/items/{item_id}/content"
    async with httpx.AsyncClient(timeout=None, follow_redirects=True) as c:
        async with c.stream("GET", url, headers=_headers()) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
    return dest_path


async def send_mail(sender: str, to_upns: list[str], subject: str, html_body: str) -> None:
    """Send an HTML email on behalf of *sender* to one or more recipients.

    Requires the app to have the ``Mail.Send`` application permission in Entra ID.
    The message is saved to the sender's Sent Items folder.
    """
    if _mock_enabled():
        return

    url = f"{settings.graph_base}/users/{sender}/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to_upns],
        },
        "saveToSentItems": True,
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, headers=_headers(), json=payload)
        r.raise_for_status()


async def get_upcoming_calendar_events(upn: str, days: int = 7) -> list[dict]:
    """Return the user's online meetings (Teams) for the next `days` days."""
    if _mock_enabled():
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        end = start + timedelta(minutes=45)
        return [{
            "id": "mock-calendar-quarterly-planning",
            "subject": "Quarterly Planning (Mock)",
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
            "organizer": {"emailAddress": {
                "name": upn.split("@", 1)[0].replace(".", " ").title(),
                "address": upn,
            }},
            "attendees": [{"emailAddress": {
                "name": "Demo Colleague",
                "address": "demo.colleague@taxconsulting.co.za",
            }}],
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
            "location": {"displayName": "Microsoft Teams Meeting"},
        }]

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    url = (
        f"{settings.graph_base}/users/{upn}/calendarView"
        f"?startDateTime={now.strftime(fmt)}"
        f"&endDateTime={end.strftime(fmt)}"
        f"&$select=id,subject,start,end,originalStartTimeZone,organizer,attendees,isOnlineMeeting,onlineMeetingProvider,location"
        f"&$orderby=start/dateTime"
        f"&$top=50"
    )
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers={**_headers(), "Prefer": 'outlook.timezone="UTC"'})
        r.raise_for_status()
        events = r.json().get("value", [])
    return [e for e in events if e.get("isOnlineMeeting")]


async def get_event_attendees(drive_id: str, drive_item_id: str) -> list[str]:
    """Best-effort: Teams recordings carry attendee metadata in SharePoint list-item fields.
    Falls back to empty list if the metadata isn't present."""
    if _mock_enabled():
        owner_upn = drive_id.removeprefix("mock-drive::")
        if not owner_upn or owner_upn == drive_id:
            owner_upn = "demo.user@taxconsulting.co.za"
        return [
            owner_upn,
            "demo.colleague@taxconsulting.co.za",
        ]

    try:
        url = (
            f"{settings.graph_base}/drives/{drive_id}"
            f"/items/{drive_item_id}/listItem?$expand=fields($select=Attendees)"
        )
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, headers=_headers())
            if r.status_code != 200:
                return []
            data = r.json()
            raw = (data.get("fields") or {}).get("Attendees", "")
            if not raw:
                return []
            return [a.strip() for a in raw.split(";") if "@" in a]
    except Exception:
        return []
