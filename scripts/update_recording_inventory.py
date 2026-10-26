"""Scoped maintenance of the existing inventory, using the same tested update stages.

Credentials stay in memory; backups/reports belong in an ignored private folder.
No meeting output, task or permission writes are issued by these stages.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from inspect_recording_discovery import railway_json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,default=str,indent=2),encoding="utf-8")


async def main(args):
    variables=railway_json("variables","--service","e1ac0606-9576-4bf7-b0b2-c414d90c46de","--environment","production")
    assert variables["RAILWAY_PROJECT_NAME"]=="meeting-intel-staging"
    os.environ.update({k:str(v) for k,v in variables.items() if v is not None})
    url=variables["DATABASE_URL"]
    if ".railway.internal" in url:
        url=railway_json("variables","--service","Postgres","--environment","production")["DATABASE_PUBLIC_URL"]
    if args.mode=="migrate":
        completed=subprocess.run([sys.executable,"-m","alembic","upgrade","81c5f02a9d31"],
            env=dict(os.environ,DATABASE_URL=url),capture_output=True,text=True,timeout=45)
        if completed.returncode:
            raise RuntimeError("Migration failed")
        print('{"migration":"81c5f02a9d31","status":"complete"}',flush=True)
        return
    from sqlalchemy import text,select
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.database import create_database_engine
    from app.models import RegisteredUser
    from app.services.recording_update import run_stage
    engine=create_database_engine(url,connect_args={"timeout":15})
    Session=async_sessionmaker(engine,expire_on_commit=False)
    inventory=json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    owners=sorted({r["owner_upn"] for r in inventory["records"] if r.get("owner_upn")})
    folder=Path(args.folder);folder.mkdir(parents=True,exist_ok=True)

    async def snapshot():
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            rows=(await conn.execute(text("""SELECT p.drive_item_id,p.drive_id,p.filename,p.identity_json
                FROM processed_items p JOIN registered_users u ON u.graph_drive_id=p.drive_id
                WHERE u.upn=ANY(:owners) ORDER BY p.drive_item_id"""),{"owners":owners})).mappings().all()
            hashes={}
            for table in ("meetings","recording_jobs","meeting_participants","action_items","meeting_email_audits"):
                hashes[table]=await conn.scalar(text(
                    f"SELECT md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY t.id),'')) FROM {table} t"))
            return {"rows":[dict(r) for r in rows],"protected":hashes}
    try:
        before=await snapshot()
        if args.mode=="backup":
            if (folder/"before.json").exists():
                raise RuntimeError("Backup already exists; never overwrite")
            write(folder/"before.json",before)
            print(json.dumps({"backed_up":len(before["rows"])}),flush=True)
            return
        if not (folder/"before.json").exists():
            raise RuntimeError("Create the backup first")
        if args.mode=="rollback":
            original=json.loads((folder/"before.json").read_text(encoding="utf-8"))
            after=json.loads((folder/"after.json").read_text(encoding="utf-8"))
            expected={r["drive_item_id"]:r for r in after["rows"]}
            async with engine.begin() as conn:
                for row in original["rows"]:
                    current=(await conn.execute(text("SELECT filename,identity_json FROM processed_items WHERE drive_item_id=:item FOR UPDATE"),{"item":row["drive_item_id"]})).mappings().one()
                    last=expected[row["drive_item_id"]]
                    if current["filename"]!=last["filename"] or current["identity_json"]!=last["identity_json"]:
                        raise RuntimeError("Identity changed after update; refusing rollback")
                    await conn.execute(text("UPDATE processed_items SET filename=:name,identity_json=CAST(:identity AS jsonb) WHERE drive_item_id=:item AND drive_id=:drive"),
                        {"name":row["filename"],"identity":json.dumps(row["identity_json"]),"item":row["drive_item_id"],"drive":row["drive_id"]})
            print(json.dumps({"restored_existing":len(original["rows"]),"new_discoveries_preserved":True}),flush=True)
            return
        results=[]
        for upn in owners:
            for stage in ("calendar","discovery","matching"):
                async with Session() as db:
                    user=await db.scalar(select(RegisteredUser).where(RegisteredUser.upn==upn,RegisteredUser.is_subscribed.is_(True)))
                    if user is None:
                        continue
                    result=await run_stage(db,user,stage)
                results.append({"user":upn,**result})
                print(json.dumps({"user":upn,"stage":stage,"status":result["status"],"counts":result["counts"]}),flush=True)
            # Bounded historical backfill: each pass reads at most four windows.
            # A failed pass is not automatically retried or declared successful.
            for _ in range(5):
                if not results or results[-1]["stage"]!="matching" or results[-1]["status"]!="partial":
                    break
                if results[-1]["counts"].get("metadata_unavailable"):
                    break
                async with Session() as db:
                    user=await db.scalar(select(RegisteredUser).where(RegisteredUser.upn==upn,RegisteredUser.is_subscribed.is_(True)))
                    if user is None:
                        break
                    result=await run_stage(db,user,"matching")
                results.append({"user":upn,**result})
                print(json.dumps({"user":upn,"stage":"matching","status":result["status"],"counts":result["counts"]}),flush=True)
        after=await snapshot()
        write(folder/"after.json",after)
        write(folder/"results.json",{"steps":results,"protected_unchanged":before["protected"]==after["protected"]})
        print(json.dumps({"protected_history_unchanged":before["protected"]==after["protected"],
                          "file_count":len(after["rows"]),
                          "unresolved":sum((r["identity_json"] or {}).get("status")!="linked" for r in after["rows"]),
                          "missing_filename":sum(not r["filename"] for r in after["rows"]),
                          "missing_date":sum(not (r["identity_json"] or {}).get("recorded_at") for r in after["rows"])}),flush=True)
    finally:
        await engine.dispose()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("backup","migrate","run","rollback"))
    parser.add_argument("--inventory",required=True)
    parser.add_argument("--folder",required=True)
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as error:
        print(json.dumps({"operation_failed":type(error).__name__,"credentials_omitted":True}),flush=True)
        sys.exit(1)
