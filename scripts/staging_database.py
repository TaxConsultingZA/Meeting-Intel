"""Staging schema inspection/migration. Read service variables as JSON on stdin.

Never log connection strings, credentials, user identities or meeting text.
Usage: railway variables --service meeting-intel-api --json | python scripts/staging_database.py inspect
"""
import asyncio
import json
import os
from pathlib import Path
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def inspect(url):
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            columns = (await conn.execute(text("""
                SELECT table_name, column_name FROM information_schema.columns
                WHERE table_schema='public' AND table_name IN
                ('recording_jobs','meetings','meeting_participants','meeting_email_audits')
                ORDER BY table_name,ordinal_position
            """))).all()
            counts = {}
            fingerprints = {}
            for table in ("meetings", "recording_jobs", "action_items", "meeting_participants"):
                counts[table] = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
                if table != "recording_jobs":  # Schema additions change the job JSON representation.
                    fingerprints[table] = await conn.scalar(text(f"SELECT md5(coalesce(string_agg(md5(row_to_json(t)::text), '' ORDER BY id),'')) FROM {table} t"))
            duplicates = await conn.scalar(text("""SELECT count(*) FROM (
                SELECT drive_item_id FROM recording_jobs WHERE status IN ('pending','processing')
                GROUP BY drive_item_id HAVING count(*)>1) d"""))
            enum_labels = (await conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON enumtypid=pg_type.oid WHERE typname='processingstate' ORDER BY enumsortorder"))).scalars().all()
            jobs = (await conn.execute(text("SELECT status,count(*) FROM recording_jobs GROUP BY status"))).all()
            zones = (await conn.execute(text("""SELECT raw->'start'->>'timeZone',count(*)
                FROM synced_calendar_events GROUP BY 1"""))).all()
            indexes = (await conn.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE tablename='recording_jobs'"))).all()
            print(json.dumps(dict(version=version, counts=counts, fingerprints=fingerprints,
                                 duplicate_active_items=duplicates, processing_states=enum_labels, jobs=[list(r) for r in jobs],
                                 calendar_timezones=[list(r) for r in zones],
                                 columns=[list(r) for r in columns], indexes=[list(r) for r in indexes])))
    finally:
        await engine.dispose()


async def graph_dates(url):
    """Read-only Graph probe; omit identities, subjects, IDs and all credentials."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            upn = await conn.scalar(text("SELECT upn FROM registered_users ORDER BY registered_at LIMIT 1"))
        from app.graph.client import get_upcoming_calendar_events
        from app.utils.timezones import utc_iso
        events = await get_upcoming_calendar_events(upn)
        print(json.dumps({"graph_calendar_read": "ok", "event_count": len(events), "date_samples": [
            {"start": e.get("start"), "end": e.get("end"),
             "originalStartTimeZone": e.get("originalStartTimeZone"), "normalized_start": utc_iso(e.get("start"))}
            for e in events[:2]]}))
    finally:
        await engine.dispose()


def main():
    variables = json.load(sys.stdin)
    url = variables["DATABASE_URL"]
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
    os.environ.update({str(k): str(v) for k, v in variables.items()})
    os.environ["DATABASE_URL"] = url
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if sys.argv[1] == "inspect":
        asyncio.run(inspect(url))
    elif sys.argv[1] == "graph-dates":
        asyncio.run(graph_dates(url))
    elif sys.argv[1] == "migrate":
        # Only explicit target revisions, never an implicit moving 'head'.
        target = sys.argv[2]
        from alembic.config import Config
        from alembic import command
        command.upgrade(Config("alembic.ini"), target)
    else:
        raise ValueError("Use inspect, graph-dates or migrate REVISION")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Database operation failed ({type(exc).__name__}); credentials omitted", file=sys.stderr)
        sys.exit(1)
