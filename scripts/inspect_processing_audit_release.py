"""Read-only release gate. Railway JSON on stdin; never print credentials/content."""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from app.database import create_database_engine

async def main():
    variables = json.load(sys.stdin)
    engine = create_database_engine(variables["DATABASE_URL"])
    try:
        async with engine.connect() as db:
            await db.execute(text("SET TRANSACTION READ ONLY"))
            result = {"head": list((await db.execute(text("select version_num from alembic_version"))).scalars()),
                "active_jobs": await db.scalar(text("select count(*) from recording_jobs where status in ('pending','processing')")),
                "audit_table": await db.scalar(text("select to_regclass('public.audit_events') is not null"))}
            if result["audit_table"]:
                result["events"] = [dict(row._mapping) for row in (await db.execute(text("select event_type,outcome,count(*) as count from audit_events group by 1,2 order by 1,2"))).all()]
                result["unique_keys"] = await db.scalar(text("select count(*) = count(distinct event_key) from audit_events"))
                result["required_fields"] = await db.scalar(text("select count(*)=0 from audit_events where occurred_at is null or actor_id is null or resource_id is null or correlation_id is null"))
            result["runtime"] = {k:variables.get(k) for k in ("SERVICE_ROLE","RECORDING_PROCESSING_ENABLED","EMAILS_ENABLED","AUTO_SEND_EMAIL","BUSINESSAI_ENABLED","EXTRACTOR_IMPL")}
            print(json.dumps(result))
    finally:
        await engine.dispose()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print("Read-only audit gate failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
