"""Plan/apply/rollback an exact Graph-verified ledger identity repair.

Private backups and plans belong outside version control. This never changes
meetings, participants, reviews, action items, transcripts, summaries or jobs.
"""
import argparse
import asyncio
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from inspect_recording_discovery import railway_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding="utf-8")


async def main(args):
    variables = railway_json("variables", "--service", "e1ac0606-9576-4bf7-b0b2-c414d90c46de", "--environment", "production")
    assert variables["RAILWAY_PROJECT_NAME"] == "meeting-intel-staging"
    os.environ.update({k:str(v) for k,v in variables.items() if v is not None})
    from app.database import create_database_engine
    from sqlalchemy import text
    url = variables["DATABASE_URL"]
    if ".railway.internal" in url:
        url = railway_json("variables", "--service", "Postgres", "--environment", "production")["DATABASE_PUBLIC_URL"]
    engine = create_database_engine(url, connect_args={"timeout":15})
    folder = Path(args.folder)
    folder.mkdir(parents=True, exist_ok=True)
    plan_file, backup_file = folder/"plan.json", folder/"backup.json"
    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    ids = [r["drive_item_id"] for r in audit["records"]]

    async def fingerprint(conn):
        result = {}
        for table in ("meetings","recording_jobs","meeting_participants","action_items","meeting_email_audits"):
            result[table] = await conn.scalar(text(
                f"SELECT md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY t.id),'')) FROM {table} t"))
        return result

    try:
        if args.mode == "plan":
            async with engine.connect() as conn:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                before = (await conn.execute(text("SELECT drive_item_id,drive_id,filename,to_jsonb(p)->'identity_json' AS identity_json FROM processed_items p WHERE drive_item_id=ANY(:ids) ORDER BY drive_item_id"), {"ids":ids})).mappings().all()
                protected = await fingerprint(conn)
            backup = {"created_at":datetime.now(timezone.utc).isoformat(),"rows":[dict(r) for r in before],"protected":protected}
            originals = {r["drive_item_id"]:dict(r) for r in before}
            changes = []
            for row in audit["records"]:
                item = row.get("graph") or {}
                if item.get("id") != row["drive_item_id"] or not item.get("name","").lower().endswith(".mp4"):
                    continue
                original = originals[row["drive_item_id"]]
                if original["drive_id"] != row["drive_id"]:
                    raise RuntimeError("Drive changed since audit")
                identity = {"status":"needs_review" if row["classification"]=="historical_misassociation" else "unmatched",
                    "recorded_at":row.get("file_recorded_at"),"size":item.get("size"),
                    "evidence":"exact_graph_drive_and_item","event":None}
                changes.append({"item_id":row["drive_item_id"],"drive_id":row["drive_id"],
                    "classification":row["classification"],"before":original,
                    "after":{"filename":item["name"],"identity_json":identity}})
            save(backup_file, backup)
            save(plan_file, {"changes":changes,"backup_sha256":hashlib.sha256(backup_file.read_bytes()).hexdigest()})
            with (folder/"inventory.csv").open("w",encoding="utf-8-sig",newline="") as handle:
                writer=csv.writer(handle)
                writer.writerow(["classification","owner","original_filename","item_id","drive_id","recorded_at_utc","meeting_id","task_statuses","has_transcript","has_summary","review_state","approved_at","candidate_event_ids"])
                for r in audit["records"]:
                    writer.writerow([r["classification"],r["owner_upn"],(r.get("graph") or {}).get("name"),r["drive_item_id"],r["drive_id"],r.get("file_recorded_at"),r["meeting_id"],";".join(j["status"] for j in r["jobs"]),r["has_transcript"],r["has_summary"],r["state"],r["approved_at"],";".join(e["id"] for e in r.get("calendar_candidates",[]))])
            print(json.dumps({"planned":len(changes),"backup":str(backup_file),"plan":str(plan_file)}))
            return
        plan=json.loads(plan_file.read_text(encoding="utf-8"))
        backup=json.loads(backup_file.read_text(encoding="utf-8"))
        assert hashlib.sha256(backup_file.read_bytes()).hexdigest()==plan["backup_sha256"]
        if args.mode == "migrate":
            # This isolated additive migration is the only schema operation.
            from alembic.config import Config
            from alembic import command
            import subprocess
            migration_env = dict(os.environ, DATABASE_URL=url)
            completed = subprocess.run([sys.executable,"-m","alembic","upgrade","70b4e91f8a20"],capture_output=True,text=True,timeout=45,env=migration_env)
            if completed.returncode:
                raise RuntimeError("Identity migration failed")
            print('{"migration":"70b4e91f8a20","status":"complete"}')
            return
        async with engine.begin() as conn:
            if args.mode == "verify":
                await conn.execute(text("SET TRANSACTION READ ONLY"))
            protected_before = await fingerprint(conn)
            verified = 0
            for change in plan["changes"]:
                row = (await conn.execute(text("SELECT drive_item_id,drive_id,filename,identity_json FROM processed_items WHERE drive_item_id=:id"+(" FOR UPDATE" if args.mode!="verify" else "")),{"id":change["item_id"]})).mappings().one()
                expected = change["after"]
                if args.mode=="verify":
                    if row["filename"]!=expected["filename"] or row["identity_json"]!=expected["identity_json"]:
                        raise RuntimeError("Post-repair identity mismatch")
                else:
                    source=change["before"] if args.mode=="apply" else change["after"]
                    target=change["after"] if args.mode=="apply" else change["before"]
                    if row["filename"]!=source["filename"] or row["identity_json"]!=source["identity_json"]:
                        raise RuntimeError("Concurrent identity change; transaction rolled back")
                    await conn.execute(text("UPDATE processed_items SET filename=:filename,identity_json=CAST(:identity AS jsonb) WHERE drive_item_id=:id AND drive_id=:drive"),{
                        "filename":target["filename"],"identity":json.dumps(target["identity_json"]),
                        "id":change["item_id"],"drive":change["drive_id"]})
                verified+=1
            protected_after = await fingerprint(conn)
            if protected_after!=protected_before:
                raise RuntimeError("Protected history changed; transaction rolled back")
        save(folder/(args.mode+"-result.json"),{"records":verified,"protected_before":protected_before,"protected_after":protected_after,"protected_equal":protected_before==protected_after,"baseline_equal":protected_after==backup["protected"]})
        print(json.dumps({"mode":args.mode,"records":verified,"protected_history_unchanged":True,"baseline_equal":protected_after==backup["protected"]}))
    finally:
        await engine.dispose()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("plan","migrate","apply","rollback","verify"))
    parser.add_argument("--audit",required=True)
    parser.add_argument("--folder",required=True)
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as error:
        print(json.dumps({"repair_failed":type(error).__name__,"credentials_omitted":True}))
        sys.exit(1)
