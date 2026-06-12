"""
Diagnostic script — lists all domain users, their OneDrive ID,
and any recordings already in their Recordings folder.
No config needed beyond what's in .env.

Usage:
    python scripts/resolve_drive_id.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.graph import client as graph
from app.config import get_settings

settings = get_settings()


async def main():
    print(f"Listing all users in @{settings.allowed_domain}...\n")
    users = await graph.list_domain_users()
    print(f"Found {len(users)} user(s).\n")

    for user in users:
        upn = user.get("mail") or user.get("id")
        name = user.get("displayName", "")
        print(f"{name} <{upn}>")
        try:
            drive_id = await graph.get_user_drive_id(upn)
            print(f"  drive_id : {drive_id}")
            recordings = await graph.list_recordings_folder(drive_id)
            if recordings:
                for item in recordings:
                    size_mb = item.get("size", 0) / 1_048_576
                    print(f"  recording: {item['name']} ({size_mb:.1f} MB)  id={item['id']}")
            else:
                print("  recordings: (none yet)")
        except Exception as e:
            print(f"  ERROR: {e}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
