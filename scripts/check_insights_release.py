"""Read-only release gate. DATABASE_URL must be supplied explicitly by the operator.

Never loads .env files, migrates schema, imports app.main, or starts a worker.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from app.database import create_database_engine


async def check(args):
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL must be supplied explicitly")
    if args.local_no_tls:
        parsed = make_url(url)
        if parsed.host != "127.0.0.1" or parsed.port != 55483 or not parsed.database.startswith("meeting_insights_"):
            raise ValueError("Local mode accepts only the isolated acceptance database")
        engine = create_async_engine(url, connect_args={"ssl": False})
    else:
        engine = create_database_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            if args.local_no_tls:
                directory = Path(await conn.scalar(text("SHOW data_directory"))).resolve()
                if directory != (ROOT / "artifacts/meeting-insights/pg-data").resolve():
                    raise ValueError("Not the isolated acceptance cluster")
            heads = list((await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars())
            exists = bool(await conn.scalar(text("SELECT to_regclass('public.meeting_insight_drafts')")))
            report = {"heads": heads, "draft_table_exists": exists, "read_only": True}
            report["ok"] = heads == [args.expect_head] and exists == (args.draft_table == "present")
            print(json.dumps(report))
            return 0 if report["ok"] else 2
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-head", required=True)
    parser.add_argument("--draft-table", choices=("absent", "present"), required=True)
    parser.add_argument("--local-no-tls", action="store_true")
    args = parser.parse_args()
    try:
        return asyncio.run(check(args))
    except Exception:
        # Connection exceptions may include credentials; never print their repr.
        print(json.dumps({"ok": False, "error": "Read-only preflight failed; connection details suppressed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
