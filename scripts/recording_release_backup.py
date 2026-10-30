"""Explicit release backup and full restore drill. Dumps stay outside the workspace.

Reads the verified Neon branch; restores only to a labelled loopback Docker server.
Never prints credentials, DSNs, transcript contents or dump stderr.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.recording_release_preflight import railway_json

PRIVATE = Path('C:/Users/93547/.codex/private-backups/Meeting-Intel/20261030-recording-release')
EVIDENCE = Path(__file__).resolve().parents[1]/'artifacts/local-test-recordings/recording-release-execution-20261030'
EXPECTED = ('shiny-recipe-30189164','br-crimson-hill-b2qrut21','ep-patient-queen-b2jhut4w')
IMAGE = 'postgres:18-alpine'


async def fingerprints(conn):
    from sqlalchemy import text
    await conn.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    tables = list((await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars())
    result = {}
    for name in tables:
        quoted = '"'+name.replace('"','""')+'"'
        row = (await conn.execute(text(f"SELECT count(*) AS rows,md5(coalesce(string_agg(digest,'' ORDER BY digest),'')) AS fingerprint FROM (SELECT md5(row_to_json(t)::text) AS digest FROM public.{quoted} t) s"))).mappings().one()
        result[name] = dict(row)
    return result


async def main():
    import os
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.database import create_database_engine, normalize_database_url
    assert PRIVATE.is_dir() and PRIVATE.resolve().is_relative_to(Path('C:/Users/93547/.codex/private-backups').resolve())
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dump=PRIVATE/(run_id+'.dump')
    assert not dump.exists()
    api=railway_json('variables','--service','meeting-intel-api','--environment','production')
    worker=railway_json('variables','--service','meeting-intel-worker','--environment','production')
    assert all(v.get('RECORDING_PROCESSING_ENABLED')=='false' for v in (api,worker))
    parsed=make_url(normalize_database_url(api['DATABASE_URL']))
    assert parsed.host.endswith('.neon.tech') and '-pooler' not in parsed.host
    engine=create_database_engine(api['DATABASE_URL'],connect_args={'timeout':15})
    container='meeting-intel-restore-'+run_id.lower()
    cid=None
    record={'run_id':run_id,'backup_kind':'pg_dump custom, exported consistent snapshot',
            'restore_target':'isolated loopback Docker PostgreSQL 18; not live Neon',
            'project_id':EXPECTED[0],'branch_id':EXPECTED[1],'endpoint_id':EXPECTED[2]}
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            identity=(await conn.execute(text("SELECT current_setting('neon.project_id'),current_setting('neon.branch_id'),current_setting('neon.endpoint_id')"))).one()
            assert tuple(identity)==EXPECTED
            assert await conn.scalar(text("SELECT count(*) FROM recording_jobs WHERE status='processing'"))==0
            snapshot=await conn.scalar(text('SELECT pg_export_snapshot()'))
            record['recovery_point_utc']=str(await conn.scalar(text('SELECT transaction_timestamp()')))
            record['revision']=list((await conn.execute(text('SELECT version_num FROM alembic_version'))).scalars())
            expected=await fingerprints(conn)
            env=dict(os.environ,PGHOST=parsed.host,PGPORT=str(parsed.port or 5432),
                     PGUSER=parsed.username,PGPASSWORD=parsed.password,PGDATABASE=parsed.database,
                     PGSSLMODE='require',PGCONNECT_TIMEOUT='15')
            command=['docker','run','--rm']
            for key in ('PGHOST','PGPORT','PGUSER','PGPASSWORD','PGDATABASE','PGSSLMODE','PGCONNECT_TIMEOUT'):
                command+=['--env',key]
            command += [IMAGE,'pg_dump','--verbose','--lock-wait-timeout=15s','--format=custom','--no-owner','--no-privileges','--snapshot='+snapshot]
            with dump.open('xb') as stream, (PRIVATE/(run_id+'-dump-diagnostic.log')).open('xb') as diagnostics:
                done=await asyncio.to_thread(subprocess.run,command,env=env,stdout=stream,stderr=diagnostics,timeout=300)
            if done.returncode:raise RuntimeError('Backup command failed; output withheld')
            await conn.rollback()
        assert dump.stat().st_size>0
        record['dump_bytes']=dump.stat().st_size
        record['dump_sha256']=hashlib.sha256(dump.read_bytes()).hexdigest()
        # A generated, disposable local password is never placed in argv or logs.
        password=secrets.token_hex(24)
        env=dict(os.environ,POSTGRES_PASSWORD=password)
        launched=subprocess.run(['docker','run','--detach','--name',container,
            '--label','meeting-intel.restore-verification=true','--publish','127.0.0.1:5438:5432',
            '--env','POSTGRES_PASSWORD','--tmpfs','/var/lib/postgresql:rw,nosuid,size=512m',IMAGE],
            env=env,capture_output=True,text=True,timeout=45)
        if launched.returncode:raise RuntimeError('Isolated restore server start failed')
        cid=launched.stdout.strip()
        for _ in range(60):
            ready=subprocess.run(['docker','exec',cid,'pg_isready','-U','postgres'],capture_output=True,timeout=10)
            if ready.returncode==0:break
            await asyncio.sleep(.5)
        else:raise RuntimeError('Isolated restore server unavailable')
        with dump.open('rb') as stream:
            restored=await asyncio.to_thread(subprocess.run,['docker','exec','-i',cid,'pg_restore',
                '-U','postgres','-d','postgres','--no-owner','--no-privileges','--exit-on-error'],
                stdin=stream,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
        if restored.returncode:raise RuntimeError('Restore command failed; output withheld')
        local=create_async_engine('postgresql+asyncpg://postgres:'+password+'@127.0.0.1:5438/postgres',connect_args={'ssl':False})
        try:
            async with local.connect() as conn:
                await conn.execute(text('SET TRANSACTION READ ONLY'))
                actual=await fingerprints(conn)
                await conn.rollback()
        finally:await local.dispose()
        assert actual==expected, 'Restored row counts or fingerprints differ'
        record.update(restore_verified=True,table_count=len(expected),tables=expected,
            backup_location='restricted private-backups directory, outside repository',
            ownership_and_grants='portable data/schema backup; restore uses target-local owner, no source grants')
        print(json.dumps({'backup_complete':True,'restore_verified':True,'tables':len(expected),
            'dump_bytes':record['dump_bytes'],'recovery_point_utc':record['recovery_point_utc']}))
    finally:
        await engine.dispose()
        if cid:
            info=json.loads(subprocess.check_output(['docker','inspect',cid]))[0]
            assert info['Name']=='/'+container and info['Config']['Labels'].get('meeting-intel.restore-verification')=='true'
            removed=subprocess.run(['docker','rm','--force','--volumes',cid],capture_output=True,timeout=45)
            record['restore_container_removed']=removed.returncode==0
        EVIDENCE.mkdir(parents=True,exist_ok=True)
        (EVIDENCE/('backup-restore-'+run_id+'.json')).write_text(json.dumps(record,default=str,indent=2),encoding='utf-8')
        (EVIDENCE/'backup-restore-result.json').write_text(json.dumps(record,default=str,indent=2),encoding='utf-8')


if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'backup_or_restore_failed':True,'error_type':type(exc).__name__,'details_suppressed':True}))
        sys.exit(1)
