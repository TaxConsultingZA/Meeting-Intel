"""Explicit release backup/migration gates; secrets remain in process memory.

Backups and restore data stay in an ACL-restricted directory outside the repo.
Never changes service variables, invokes a provider, or starts a worker.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.recording_release_preflight import railway_json
from scripts.recording_release_backup import fingerprints

PRIVATE = Path('C:/Users/93547/.codex/private-backups/Meeting-Intel/20261103-insights-release')
EVIDENCE = ROOT / 'artifacts/insights-release-execution'
BIN = Path('C:/Users/93547/.codex/cache/postgresql-18.6-release-client/pgsql/bin')
EXPECTED = ('shiny-recipe-30189164', 'br-crimson-hill-b2qrut21', 'ep-patient-queen-b2jhut4w')
HEAD = '92d6a10f4e72'
TARGET = '62e9a3b8d014'


def service_values():
    api = railway_json('variables', '--service', 'meeting-intel-api', '--environment', 'production')
    assert api.get('RAILWAY_PROJECT_ID') == '059e3add-9746-4baa-90e1-58d4fa5f2559'
    return api


def save(name, data):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(data, indent=2, default=str) + '\n', encoding='utf-8')


def run_native(args, *, env=None, log=None, timeout=120):
    with log.open('ab') as stream:
        result = subprocess.run([str(a) for a in args], env=env, stdout=stream, stderr=stream,
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Native backup/restore operation failed; diagnostics remain private')


async def backup():
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.database import create_database_engine, normalize_database_url
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = PRIVATE / run_id
    folder.mkdir(parents=True, exist_ok=False)
    account = subprocess.check_output(['whoami'], text=True).strip()
    acl = subprocess.run(['icacls', str(folder), '/inheritance:r', '/grant:r',
        account + ':(OI)(CI)F', 'SYSTEM:(OI)(CI)F'], capture_output=True)
    assert acl.returncode == 0
    api = service_values()
    parsed = make_url(normalize_database_url(api['DATABASE_URL']))
    assert parsed.host.endswith('.neon.tech') and '-pooler' not in parsed.host
    engine = create_database_engine(api['DATABASE_URL'], connect_args={'timeout': 15})
    dump = folder / 'database.dump'
    diagnostic = folder / 'private-diagnostics.log'
    record = {'run_id': run_id, 'kind': 'pg_dump custom with exported consistent snapshot',
        'backup_location': 'ACL-restricted private-backups outside repository', 'worker_paused': False}
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            identity = (await conn.execute(text("SELECT current_setting('neon.project_id'),current_setting('neon.branch_id'),current_setting('neon.endpoint_id')"))).one()
            assert tuple(identity) == EXPECTED
            assert list((await conn.execute(text('SELECT version_num FROM alembic_version'))).scalars()) == [HEAD]
            snapshot = await conn.scalar(text('SELECT pg_export_snapshot()'))
            record['recovery_point_utc'] = str(await conn.scalar(text('SELECT transaction_timestamp()')))
            expected = await fingerprints(conn)
            env = dict(os.environ, PGHOST=parsed.host, PGPORT=str(parsed.port or 5432),
                PGUSER=parsed.username, PGPASSWORD=parsed.password, PGDATABASE=parsed.database,
                PGSSLMODE='require', PGCONNECT_TIMEOUT='15')
            with diagnostic.open('ab') as log:
                result = await asyncio.to_thread(subprocess.run,
                    [str(BIN / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-privileges',
                     '--lock-wait-timeout=15s', '--snapshot=' + snapshot, '--file=' + str(dump)],
                    env=env, stdout=log, stderr=log, timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode == 0 and dump.stat().st_size > 0
            await conn.rollback()
        record['dump_bytes'] = dump.stat().st_size
        record['dump_sha256'] = hashlib.sha256(dump.read_bytes()).hexdigest()
        data = folder / 'restore-data'
        pwfile = folder / 'restore-password.tmp'
        password = secrets.token_hex(24)
        pwfile.write_text(password + '\n', encoding='utf-8')
        run_native([BIN / 'initdb.exe', '-D', data, '-U', 'postgres', '-A', 'scram-sha-256',
            '--pwfile=' + str(pwfile), '--no-locale', '--encoding=UTF8'], log=diagnostic)
        pwfile.unlink()
        started = False
        try:
            run_native([BIN / 'pg_ctl.exe', '-D', data, '-l', folder / 'restore-server.log',
                '-o', '-p 55484 -h 127.0.0.1', '-w', 'start'], log=diagnostic)
            started = True
            env = dict(os.environ, PGPASSWORD=password, PGSSLMODE='disable')
            run_native([BIN / 'pg_restore.exe', '-h', '127.0.0.1', '-p', '55484', '-U', 'postgres',
                '-d', 'postgres', '--no-owner', '--no-privileges', '--exit-on-error', dump], env=env, log=diagnostic)
            local = create_async_engine('postgresql+asyncpg://postgres:' + password + '@127.0.0.1:55484/postgres', connect_args={'ssl': False})
            try:
                async with local.connect() as conn:
                    await conn.execute(text('SET TRANSACTION READ ONLY'))
                    assert Path(await conn.scalar(text('SHOW data_directory'))).resolve() == data.resolve()
                    assert await fingerprints(conn) == expected
            finally:
                await local.dispose()
        finally:
            if started:
                run_native([BIN / 'pg_ctl.exe', '-D', data, '-m', 'fast', '-w', 'stop'], log=diagnostic)
        record.update(restore_verified=True, table_count=len(expected), head=HEAD)
        state = dict(record, dump=str(dump), diagnostic=str(diagnostic))
        (folder / 'state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        (PRIVATE / 'latest.json').write_text(json.dumps({'folder': str(folder)}), encoding='utf-8')
        save('backup.json', record)
        print(json.dumps(record))
    finally:
        await engine.dispose()


async def migrate(commit):
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == commit
    assert not subprocess.check_output(['git', 'diff', 'HEAD', '--', 'app', 'alembic', 'scripts/check_insights_release.py'], cwd=ROOT).strip()
    folder = Path(json.loads((PRIVATE / 'latest.json').read_text())['folder'])
    assert folder.resolve().is_relative_to(PRIVATE.resolve())
    state = json.loads((folder / 'state.json').read_text())
    assert state['restore_verified'] and state['head'] == HEAD
    assert hashlib.sha256(Path(state['dump']).read_bytes()).hexdigest() == state['dump_sha256']
    api = service_values()
    env = dict(os.environ, **api)
    for name in env:
        assert isinstance(env[name], str)
    steps = [
        ['scripts/check_insights_release.py', '--expect-head', HEAD, '--draft-table', 'absent'],
        ['-m', 'alembic', 'upgrade', TARGET],
        ['scripts/check_insights_release.py', '--expect-head', TARGET, '--draft-table', 'present'],
    ]
    results = []
    for index, step in enumerate(steps):
        result = subprocess.run([sys.executable, *step], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=120)
        with Path(state['diagnostic']).open('a', encoding='utf-8') as stream:
            stream.write(result.stdout + result.stderr)
        results.append({'step': index, 'exit_code': result.returncode})
        save('migration.json', {'commit': commit, 'from': HEAD, 'target': TARGET, 'steps': results})
        if result.returncode:
            raise RuntimeError('Release gate or migration failed; stop without retry or stamp')
    print(json.dumps({'migration_complete': True, 'from': HEAD, 'target': TARGET, 'steps': results}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'migrate'])
    parser.add_argument('--commit')
    args = parser.parse_args()
    try:
        asyncio.run(backup() if args.operation == 'backup' else migrate(args.commit))
    except Exception as exc:
        print(json.dumps({'release_stopped': True, 'error_type': type(exc).__name__, 'details_suppressed': True}))
        raise SystemExit(1)
