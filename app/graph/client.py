import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from .auth import get_token
from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

RECORDINGS_TRAVERSAL_MAX_DEPTH = 2
RECORDINGS_TRAVERSAL_MAX_REQUESTS = 100
RECORDINGS_TRAVERSAL_MAX_FOLDERS = 100
_FOLDER_METADATA_SELECT = "$select=id,name,folder,parentReference"


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


async def list_recordings_folder(drive_id: str, *, strict: bool = False) -> list[dict]:
    """List mp4 files in every Recordings folder in the given drive.

    Known paths are checked first.  A bounded two-level traversal then finds
    other common placements without using Graph search or walking the drive
    without limits.
    """
    if _mock_enabled():
        return [{
            "id": f"{drive_id}::recording-past-untranscribed",
            "name": "Past Client Update - Untranscribed.mp4",
            "size": 9_437_184,
            "createdDateTime": "2026-07-15T09:30:00Z",
            "eTag": '"mock-etag-past-1"',
        }]

    drive_url = f"{settings.graph_base}/drives/{drive_id}"

    async def collect_mp4_children(
        client: httpx.AsyncClient,
        initial_url: str,
        recordings_by_id: dict[str, dict],
        *,
        ignore_forbidden: bool = False,
        branch_name: str = "Recordings folder",
    ) -> None:
        url: str | None = initial_url
        seen_urls: set[str] = set()
        while url and url not in seen_urls:
            seen_urls.add(url)
            response = await client.get(url, headers=_headers())
            if response.status_code == 404:
                return
            if response.status_code == 403 and ignore_forbidden and not strict:
                logger.warning(
                    "Skipped inaccessible optional OneDrive branch: %s",
                    branch_name,
                )
                return
            response.raise_for_status()
            data = response.json()
            for item in data.get("value", []):
                if item.get("name", "").endswith(".mp4") and item.get("id"):
                    recordings_by_id[item["id"]] = item
            url = data.get("@odata.nextLink")

    async def discover_recordings_folder_ids(
        client: httpx.AsyncClient,
    ) -> list[str]:
        root_url = f"{drive_url}/root/children?{_FOLDER_METADATA_SELECT}"
        queue: list[tuple[str, int]] = [(root_url, 0)]
        queued_folder_ids: set[str] = set()
        recording_folder_ids: list[str] = []
        recording_folder_id_set: set[str] = set()
        request_count = 0
        folder_count = 0

        queue_index = 0
        while queue_index < len(queue):
            url, parent_depth = queue[queue_index]
            queue_index += 1
            seen_page_urls: set[str] = set()

            while url and url not in seen_page_urls:
                if request_count >= RECORDINGS_TRAVERSAL_MAX_REQUESTS:
                    if strict:
                        raise RuntimeError("OneDrive discovery incomplete")
                    logger.warning(
                        "Stopped OneDrive folder traversal at request limit %s",
                        RECORDINGS_TRAVERSAL_MAX_REQUESTS,
                    )
                    return recording_folder_ids
                seen_page_urls.add(url)
                request_count += 1
                response = await client.get(url, headers=_headers())
                if response.status_code == 404:
                    break
                if response.status_code == 403 and parent_depth > 0 and not strict:
                    logger.warning(
                        "Skipped inaccessible optional OneDrive traversal branch"
                    )
                    break
                response.raise_for_status()
                data = response.json()

                for item in data.get("value", []):
                    if item.get("folder") is None:
                        continue
                    if folder_count >= RECORDINGS_TRAVERSAL_MAX_FOLDERS:
                        if strict:
                            raise RuntimeError("OneDrive discovery incomplete")
                        logger.warning(
                            "Stopped OneDrive folder traversal at folder limit %s",
                            RECORDINGS_TRAVERSAL_MAX_FOLDERS,
                        )
                        return recording_folder_ids
                    folder_count += 1

                    folder_id = item.get("id")
                    if not folder_id:
                        continue
                    item_depth = parent_depth + 1
                    if item.get("name", "").casefold() == "recordings":
                        if folder_id not in recording_folder_id_set:
                            recording_folder_id_set.add(folder_id)
                            recording_folder_ids.append(folder_id)
                    elif (
                        item_depth < RECORDINGS_TRAVERSAL_MAX_DEPTH
                        and folder_id not in queued_folder_ids
                    ):
                        queued_folder_ids.add(folder_id)
                        queue.append((
                            f"{drive_url}/items/{folder_id}/children"
                            f"?{_FOLDER_METADATA_SELECT}",
                            item_depth,
                        ))

                url = data.get("@odata.nextLink")

        return recording_folder_ids

    recordings_by_id: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=30) as c:
        await collect_mp4_children(
            c,
            f"{drive_url}/root:/Recordings:/children",
            recordings_by_id,
        )
        await collect_mp4_children(
            c,
            f"{drive_url}/root:/Documents/Recordings:/children",
            recordings_by_id,
            ignore_forbidden=True,
            branch_name="Documents/Recordings",
        )

        for folder_id in await discover_recordings_folder_ids(c):
            await collect_mp4_children(
                c,
                f"{drive_url}/items/{folder_id}/children",
                recordings_by_id,
                ignore_forbidden=True,
                branch_name="discovered Recordings folder",
            )

    return list(recordings_by_id.values())


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


async def get_upcoming_calendar_events(upn: str, days: int = 7, *, include_offline: bool = False) -> list[dict]:
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
    start = now - timedelta(days=7)
    end = now + timedelta(days=days)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    url = (
        f"{settings.graph_base}/users/{upn}/calendarView"
        f"?startDateTime={start.strftime(fmt)}"
        f"&endDateTime={end.strftime(fmt)}"
        f"&$select=id,iCalUId,isCancelled,subject,start,end,originalStartTimeZone,organizer,attendees,isOnlineMeeting,onlineMeetingProvider,location"
        f"&$orderby=start/dateTime"
        f"&$top=50"
    )
    events = await _calendar_pages(url)
    return events if include_offline else [e for e in events if e.get("isOnlineMeeting")]


async def _calendar_pages(url: str) -> list[dict]:
    events: list[dict] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=30) as c:
        while url:
            if url in seen or not url.startswith(settings.graph_base.rstrip("/") + "/"):
                raise RuntimeError("Invalid Calendar pagination")
            seen.add(url)
            r = await c.get(url, headers={**_headers(), "Prefer": 'outlook.timezone="UTC"'})
            r.raise_for_status()
            data = r.json()
            events.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
    return events


async def get_calendar_event(upn: str, event_id: str) -> dict:
    """Read an event in the authenticated mailbox, including after the recent window."""
    if _mock_enabled():
        events = await get_upcoming_calendar_events(upn, include_offline=True)
        return next((e for e in events if e["id"] == event_id), {})
    url = f"{settings.graph_base}/users/{quote(upn, safe='')}/events/{quote(event_id, safe='')}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers={**_headers(), "Prefer": 'outlook.timezone="UTC"'})
        r.raise_for_status()
        return r.json()


async def get_calendar_window(upn: str, start: datetime, end: datetime) -> list[dict]:
    if _mock_enabled():
        return await get_upcoming_calendar_events(upn, include_offline=True)
    return await _calendar_pages(
        f"{settings.graph_base}/users/{quote(upn, safe='')}/calendarView"
        f"?startDateTime={quote(start.isoformat())}&endDateTime={quote(end.isoformat())}"
        "&$select=id,iCalUId,isCancelled,subject,start,end,organizer,attendees&$top=100"
    )


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
