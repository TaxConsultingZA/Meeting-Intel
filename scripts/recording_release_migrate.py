"""Bounded explicit migration for a separately approved release; default is read-only.

Run from the reviewed source root via Railway run. Never prints settings or SQL errors.
Backup flags are operator attestations, not an automated backup/restore verification.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
BASE = '51d8f2a7c903'
TARGET = '92d6a10f4e72'


async def inspect(url):
    from app.database import create_database_engine
    from sqlalchemy import text
    engine = create_database_engine(url, connect_args={'timeout':15,
        'server_settings':{'lock_timeout':'5s','statement_timeout':'60s'}})
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            revisions = list((await conn.execute(text('SELECT version_num FROM alembic_version'))).scalars())
            processing = await conn.scalar(text("SELECT count(*) FROM recording_jobs WHERE status='processing'"))
            await conn.rollback()
            return revisions, processing
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-reference')
    parser.add_argument('--restore-verified', action='store_true')
    args = parser.parse_args()
    if not Path('alembic.ini').is_file():
        raise RuntimeError('Use reviewed source root')
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError('Database environment required')
    revisions, processing = asyncio.run(inspect(url))
    if not args.apply:
        print(json.dumps({'read_only':True,'revisions':revisions,'processing_jobs':processing}))
        return
    if not args.backup_reference or not args.restore_verified:
        raise RuntimeError('Verified backup/restore attestation required')
    for name in ('RECORDING_PROCESSING_ENABLED','EMAILS_ENABLED','AUTO_SEND_EMAIL','ENABLE_AUTO_RECONCILE'):
        if os.environ.get(name,'').strip().lower() != 'false':
            raise RuntimeError('Explicit disabled settings required')
    if os.environ.get('SERVICE_ROLE') != 'api' or os.environ.get('EXTRACTOR_IMPL') != 'transcript_only':
        raise RuntimeError('Approved API environment required')
    if revisions != [BASE] or processing:
        raise RuntimeError('Migration baseline or idle prerequisite changed')
    from alembic.config import Config
    from alembic import command
    from alembic.script import ScriptDirectory
    import app.database
    config = Config('alembic.ini')
    if ScriptDirectory.from_config(config).get_heads() != [TARGET]:
        raise RuntimeError('Reviewed single migration head required')
    original = app.database.create_database_engine
    def bounded(value, **options):
        # Applied to the connection Alembic itself creates, rather than relying
        # on libpq PGOPTIONS (which asyncpg does not consume).
        options['connect_args'] = {'timeout':15,
            'server_settings':{'lock_timeout':'5s','statement_timeout':'60s'}}
        return original(value, **options)
    app.database.create_database_engine = bounded
    try:
        command.upgrade(config, TARGET)
    finally:
        app.database.create_database_engine = original
    revisions, processing = asyncio.run(inspect(url))
    if revisions != [TARGET] or processing:
        raise RuntimeError('Post-migration verification failed; keep processing disabled')
    print(json.dumps({'migrated_to':TARGET,'processing_jobs':processing,
        'backup_restore_attested':True,'processing_enabled':False}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'details_suppressed':True}))
        sys.exit(1)
