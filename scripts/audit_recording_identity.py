"""GET/SELECT-only inventory of Unknown recordings and an explicit case item."""
import asyncio
import json
import os
from pathlib import Path
import sys
from datetime import timedelta

from inspect_recording_discovery import railway_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
OUTPUT = Path(__file__).resolve().parents[1] / "artifacts/local-test-recordings/identity-audit.json"


async def main():
    variables = railway_json("variables", "--service", "e1ac0606-9576-4bf7-b0b2-c414d90c46de", "--environment", "production")
    assert variables["RAILWAY_PROJECT_NAME"] == "meeting-intel-staging"
    os.environ.update({k: str(v) for k, v in variables.items() if v is not None})
    from app.database import create_database_engine
    from sqlalchemy import text
    from app.graph import client as graph
    from app.services.meeting_matching import recording_datetime, match_calendar_event
    from app.utils.timezones import parse_graph_datetime
    url = variables["DATABASE_URL"]
    if ".railway.internal" in url:
        url = railway_json("variables", "--service", "Postgres", "--environment", "production")["DATABASE_PUBLIC_URL"]
    engine = create_database_engine(url, connect_args={"timeout": 15})
    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await conn.execute(text("""
            SELECT p.drive_item_id,p.drive_id,p.filename,p.first_seen_at,
                   u.upn AS owner_upn,u.is_subscribed,m.id AS meeting_id,m.title,m.recorded_at,m.state,
                   length(coalesce(m.transcript,''))>0 AS has_transcript,
                   length(coalesce(m.summary,''))>0 AS has_summary,
                   m.approved_at,m.approved_by,m.organizer_upn,
                   m.extracted_json->>'outlook_event_id' AS outlook_event_id,
                   m.extracted_json->'t5_calendar_event' AS t5_calendar_event,
                   m.extracted_json->'recording_identity' AS recording_identity,
                   (SELECT coalesce(json_agg(json_build_object('id',j.id,'status',j.status,'source',j.source)), '[]')
                      FROM recording_jobs j WHERE j.drive_item_id=p.drive_item_id) AS jobs
            FROM processed_items p
            LEFT JOIN meetings m ON m.drive_item_id=p.drive_item_id
            LEFT JOIN registered_users u ON u.graph_drive_id=p.drive_id
            WHERE lower(coalesce(nullif(trim(m.title),''),nullif(trim(p.filename),''),'Unknown'))='unknown'
               OR p.drive_item_id='01LIX265JFMJPO3YO52BELGAXDCTWU7SPI'
            ORDER BY u.upn,p.first_seen_at
        """))).mappings().all()
        records = [dict(r) for r in rows]
    await engine.dispose()
    result = {"flags": {k: variables.get(k) for k in ("ENABLE_SCHEDULED_SYNC", "ENABLE_AUTO_RECONCILE")}, "records": records}
    for row in records:
        try:
            item = await graph.get_drive_item(row["drive_id"], row["drive_item_id"])
            row["graph"] = {k: item.get(k) for k in ("id","name","size","createdDateTime","lastModifiedDateTime","parentReference","fileSystemInfo")}
            instant = recording_datetime(item.get("name", ""), item)
            row["file_recorded_at"] = instant
            if not row["owner_upn"] or not instant:
                row["classification"] = "insufficient_file_or_owner_evidence"
                continue
            events = await graph.get_calendar_window(row["owner_upn"], instant-timedelta(days=2), instant+timedelta(days=2))
            # Save event identity + time evidence, never attendees or transcript.
            candidates = [e for e in events if e.get("id")==row["outlook_event_id"] or match_calendar_event(item.get("name", ""),instant,[e])]
            row["calendar_candidates"] = [{k:e.get(k) for k in ("id","iCalUId","subject","start","end","isCancelled","organizer")} for e in candidates]
            match = match_calendar_event(item.get("name", ""),instant,events)
            row["heuristic_candidate_id"] = match.get("id") if match else None
            stable = next((e for e in candidates if e.get("id")==row["outlook_event_id"]),None)
            if row["outlook_event_id"] and (not stable or not match_calendar_event(item.get("name", ""),instant,[stable])):
                row["classification"] = "historical_misassociation"
            elif stable:
                row["classification"] = "existing_stable_calendar_identity"
            elif candidates:
                row["classification"] = "candidate_requires_owner_confirmation"
            else:
                row["classification"] = "no_matching_calendar_in_owner_window"
        except Exception as error:
            row["classification"] = "permission_or_metadata_unavailable"
            row["error_type"] = type(error).__name__
            row["http_status"] = getattr(getattr(error,"response",None),"status_code",None)
        print(json.dumps({k:row.get(k) for k in ("drive_item_id","owner_upn","title","classification","http_status")}),flush=True)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,default=str,indent=2),encoding="utf-8")
    print(json.dumps({"saved":str(OUTPUT),"records":len(records)}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(json.dumps({"audit_failed":type(error).__name__}))
        sys.exit(1)
