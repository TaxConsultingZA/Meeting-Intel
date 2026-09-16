"""Scheduled job — walks the Recordings folder of every *subscribed* domain user,
finds new recordings, and processes them inline (transcribe + extract + email).
Run on a schedule (e.g. every 15 minutes) or manually."""
import asyncio
import sys

# Force UTF-8 output so filenames with special characters don't crash on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select

from app.db import SessionLocal
from app.graph import client as graph
from app.models import RegisteredUser
from app.services.ledger import claim_item
from app.services.sync_state import record_sync_result


async def _get_subscribed_upns() -> set[str]:
    """Return only users who explicitly enabled automatic processing."""
    async with SessionLocal() as db:
        upns = await db.scalars(
            select(RegisteredUser.upn).where(RegisteredUser.is_subscribed.is_(True))
        )
        return set(upns.all())


async def reconcile() -> int:
    """Discover every subscribed user's new OneDrive MP4 recordings.

    Only users who appear in the ``registered_users`` table are scanned.  This
    prevents the reconciler from touching recordings that belong to people who
    have not been onboarded onto the platform.

    For each file found, ``claim_item`` is used as an idempotency gate — only
    files not yet in the ``processed_items`` ledger are persisted. Processing is
    queued only when a user explicitly selects a recording. The function returns
    the count of newly discovered recordings so callers can log progress.
    """
    found = 0
    subscribed_upns = await _get_subscribed_upns()
    if not subscribed_upns:
        print("No subscribed users — skipping OneDrive sync.")
        return 0

    # We already know the opted-in UPNs, so a tenant-wide directory listing is
    # unnecessary. This removes an avoidable Directory.Read.All dependency.
    print(f"Reconciling {len(subscribed_upns)} subscribed user(s)...")

    for upn in subscribed_upns:
        try:
            drive_id = await graph.get_user_drive_id(upn)
            async with SessionLocal() as db:
                subscriber = await db.scalar(
                    select(RegisteredUser).where(
                        RegisteredUser.upn == upn,
                        RegisteredUser.is_subscribed.is_(True),
                    )
                )
                if not subscriber:
                    continue
                subscriber.graph_drive_id = drive_id
                await db.commit()
            recordings = await graph.list_recordings_folder(drive_id)
        except Exception as e:
            print(f"  Skipping {upn}: {e}")
            async with SessionLocal() as db:
                await record_sync_result(db, user_upn=upn, source="onedrive", error=e)
            continue

        async with SessionLocal() as db:
            await record_sync_result(db, user_upn=upn, source="onedrive")

        for item in recordings:
            drive_item_id = item["id"]
            etag = item.get("eTag")

            async with SessionLocal() as db:
                discovered = await claim_item(
                    db,
                    drive_item_id, drive_id, etag, "reconcile",
                    filename=item.get("name"),
                )

            if discovered:
                print(f"  Discovered: {item['name']} (owner: {upn})")
                found += 1

    return found


if __name__ == "__main__":
    n = asyncio.run(reconcile())
    print(f"\nReconciliation complete — discovered {n} new recording(s).")
