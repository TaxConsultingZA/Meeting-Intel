"""Read-only production investigation. Credentials stay in process memory.

Uses the linked Railway project's named API service; never triggers sync/jobs.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def railway_json(*args):
    for attempt in range(2):
        try:
            result = subprocess.run(["railway", *args, "--json"], capture_output=True, text=True, timeout=25)
            if result.returncode == 0:
                return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            pass
    raise RuntimeError("Railway read unavailable")


async def inspect(args):
    variables = railway_json("variables", "--service", args.service, "--environment", "production")
    if variables.get("RAILWAY_PROJECT_NAME") != "meeting-intel-staging":
        raise RuntimeError("Unexpected Railway project")
    os.environ.update({k: str(v) for k, v in variables.items() if v is not None})
    from app.config import Settings
    from app.database import create_database_engine
    from sqlalchemy import text

    config = Settings(_env_file=None)
    # Resolve only the public database endpoint; never print its value.
    database_url = variables.get("DATABASE_URL", "")
    if ".railway.internal" in database_url:
        postgres = railway_json("variables", "--service", "Postgres", "--environment", "production")
        database_url = postgres.get("DATABASE_PUBLIC_URL")
        if not database_url:
            raise RuntimeError("Public read-only database connection unavailable")
    engine = create_database_engine(database_url, connect_args={"timeout": 15})
    users = []
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            users = (await conn.execute(text("""SELECT upn, display_name, is_subscribed, graph_drive_id
                FROM registered_users WHERE display_name ILIKE :name OR upn ILIKE :name"""),
                {"name": f"%{args.person}%"})).mappings().all()
            print(json.dumps({"matching_registered_users": [dict(row) for row in users]}, default=str))
            if args.item:
                for table, columns in (
                    ("processed_items", "drive_item_id,drive_id,filename,source,first_seen_at"),
                    ("meetings", "id,drive_item_id,title,state,recorded_at,organizer_upn,extracted_json->>'outlook_event_id' AS outlook_event_id,extracted_json->>'meeting_time' AS extracted_meeting_time,(extracted_json ? 't5_calendar_event') AS has_t5_calendar_event"),
                    ("recording_jobs", "id,drive_item_id,drive_id,owner_upn,status,source"),
                ):
                    rows = (await conn.execute(text(f"SELECT {columns} FROM {table} WHERE drive_item_id=:item"),
                        {"item": args.item})).mappings().all()
                    print(json.dumps({"item_lookup_table": table, "rows": [dict(r) for r in rows]}, default=str))
                rows = (await conn.execute(text("""SELECT user_upn,event_id,subject,starts_at,ends_at,
                    raw->>'isCancelled' AS is_cancelled FROM synced_calendar_events
                    WHERE user_upn IN (SELECT upn FROM registered_users WHERE display_name ILIKE :name OR upn ILIKE :name)
                    AND starts_at >= '2026-09-01T00:00:00Z' AND starts_at < '2026-09-02T00:00:00Z'
                    AND (subject ILIKE :title OR event_id IN (SELECT extracted_json->>'outlook_event_id' FROM meetings WHERE drive_item_id=:item))"""),
                    {"name": f"%{args.person}%", "title": f"%{args.title}%", "item": args.item})).mappings().all()
                print(json.dumps({"cached_calendar_case_date": [dict(r) for r in rows]}, default=str))
            for user in users:
                states = (await conn.execute(text("""SELECT source,status,last_attempted_at,last_succeeded_at,
                    (last_error IS NOT NULL) AS has_error FROM user_sync_states WHERE user_upn=:upn"""),
                    {"upn": user["upn"]})).mappings().all()
                ledger = (await conn.execute(text("""SELECT p.drive_item_id,p.drive_id,p.filename,p.first_seen_at,
                    m.id AS meeting_id,m.title,m.state,m.recorded_at
                    FROM processed_items p LEFT JOIN meetings m ON m.drive_item_id=p.drive_item_id
                    WHERE p.drive_id=:drive ORDER BY p.first_seen_at"""),
                    {"drive": user["graph_drive_id"]})).mappings().all()
                print(json.dumps({"user": user["upn"], "sync_states": [dict(r) for r in states],
                    "ledger_count": len(ledger), "matching_ledger": [dict(r) for r in ledger
                    if args.title.casefold() in (str(r["filename"] or "") + str(r["title"] or "")).casefold()]}, default=str))
            await conn.rollback()
    finally:
        await engine.dispose()

    if not args.graph:
        return
    # Explicit GET-only Graph queries with the existing app registration.
    import httpx
    from app.graph.auth import get_token
    headers = {"Authorization": f"Bearer {await asyncio.to_thread(get_token)}"}
    async with httpx.AsyncClient(timeout=45) as client:
        async def get(url):
            response = await client.get(url, headers=headers)
            if response.is_error:
                print(json.dumps({"graph_error_status": response.status_code,
                                  "graph_error_code": response.json().get("error", {}).get("code")}))
                response.raise_for_status()
            return response.json()

        async def pages(url):
            rows, seen = [], set()
            while url:
                if url in seen or not url.startswith(config.graph_base.rstrip("/") + "/"):
                    raise RuntimeError("Invalid Graph pagination")
                seen.add(url)
                data = await get(url)
                rows.extend(data.get("value", []))
                url = data.get("@odata.nextLink")
            return rows

        for user in users:
            drive = await get(f"{config.graph_base}/users/{user['upn']}/drive?$select=id,driveType,webUrl,owner")
            print(json.dumps({"user": user["upn"], "graph_drive": drive,
                              "cached_drive_matches": drive["id"] == user["graph_drive_id"]}))
            base = f"{config.graph_base}/drives/{drive['id']}"
            # Search that exact user's drive, rather than all tenant users/sites.
            title = args.title.replace("'", "''")
            try:
                results = await pages(f"{base}/root/search(q='{title}')?$select=id,name,size,createdDateTime,lastModifiedDateTime,parentReference,file,folder,webUrl,remoteItem")
                print(json.dumps({"drive_search_title": args.title, "matches": results}))
            except httpx.HTTPStatusError:
                print(json.dumps({"drive_search": "unavailable; continuing exact folder reads"}))
            for path in ("Recordings", "Documents/Recordings"):
                url = f"{base}/root:/{path}:/children"
                response = await client.get(url, headers=headers)
                if response.status_code == 404:
                    print(json.dumps({"folder": path, "status": 404}))
                    continue
                if response.is_error:
                    print(json.dumps({"folder": path, "status": response.status_code}))
                    continue
                folder = await get(f"{base}/root:/{path}?$select=id,name,parentReference,webUrl")
                print(json.dumps({"folder_metadata": folder}))
                rows = await pages(url)
                safe_keys = ("id", "name", "size", "createdDateTime", "lastModifiedDateTime", "parentReference", "webUrl", "file", "folder")
                print(json.dumps({"folder": path, "children_count": len(rows), "matching_files": [{k: r[k] for k in safe_keys if k in r} for r in rows
                    if args.title.casefold() in r.get("name", "").casefold()],
                    "subfolders": [{"id": r.get("id"), "name": r.get("name")} for r in rows if "folder" in r]}))
            from app.graph.client import list_recordings_folder
            for strict in (False, True):
                try:
                    discovered = await list_recordings_folder(drive["id"], strict=strict)
                    print(json.dumps({"app_enumerator_strict": strict, "count": len(discovered),
                        "case_item_found": any(r.get("id") == args.item for r in discovered) if args.item else None,
                        "matching_ids": [r["id"] for r in discovered if args.title.casefold() in r.get("name", "").casefold()]}))
                except Exception as error:
                    print(json.dumps({"app_enumerator_strict": strict, "error_type": type(error).__name__}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="e1ac0606-9576-4bf7-b0b2-c414d90c46de")
    parser.add_argument("--person", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--graph", action="store_true")
    parser.add_argument("--item")
    try:
        asyncio.run(inspect(parser.parse_args()))
    except Exception as error:
        print(json.dumps({"inspection_failed": type(error).__name__, "credentials_omitted": True}))
        sys.exit(1)
