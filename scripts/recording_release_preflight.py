"""Read-only release evidence; never imports settings/worker or prints credentials/content."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.inspect_recording_discovery import railway_json as _railway_json

DEST = Path(__file__).resolve().parents[1] / 'artifacts/recording-release-review-20261030'
PROJECT = '059e3add-9746-4baa-90e1-58d4fa5f2559'
JOB_IDS = ('06d4341d-1edb-48ab-b6b6-ce65d9a8727d',
           '45c14cb6-88e2-4867-aab9-13da5f8e8a88', '4d468e1b-0ee5-45aa-9854-22f5700a5f05')


def railway_json(*args):
    return _railway_json(*args, '--project', PROJECT)


async def main():
    import httpx
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from app.database import create_database_engine, normalize_database_url

    services = {}
    data = {'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'mode': 'READ ONLY'}
    public = {}
    keys = ('RECORDING_PROCESSING_ENABLED', 'PROCESS_ONLY_JOB_ID', 'SERVICE_ROLE',
            'TRANSCRIBER_IMPL', 'EXTRACTOR_IMPL', 'EMAILS_ENABLED', 'AUTO_SEND_EMAIL',
            'POPIA_NOTICE_ENABLED', 'ENABLE_AUTO_RECONCILE', 'WORKER_POLL_SECONDS',
            'WORKER_LEASE_SECONDS', 'WORKER_HEARTBEAT_SECONDS', 'WORKER_SHUTDOWN_SECONDS')
    for name in ('meeting-intel-api', 'meeting-intel-worker'):
        values = railway_json('variables', '--service', name, '--environment', 'production')
        assert values.get('RAILWAY_PROJECT_NAME') == 'meeting-intel-staging'
        services[name] = values
        public[name] = {key: values.get(key, '<unset: uses code default>') for key in keys}
        public[name]['assemblyai_key_present'] = bool(values.get('ASSEMBLYAI_API_KEY'))
    data['configuration'] = public
    api, worker = (services[name] for name in ('meeting-intel-api', 'meeting-intel-worker'))
    data['project_id'] = api.get('RAILWAY_PROJECT_ID')
    data['same_provider_key'] = bool(api.get('ASSEMBLYAI_API_KEY')) and api.get('ASSEMBLYAI_API_KEY') == worker.get('ASSEMBLYAI_API_KEY')
    def identity(value):
        parsed = make_url(normalize_database_url(value))
        return parsed.host, parsed.port or 5432, parsed.database
    parsed = make_url(normalize_database_url(api['DATABASE_URL']))
    host = parsed.host or ''
    data['database'] = {
        'api_worker_endpoint_equal': identity(api['DATABASE_URL']) == identity(worker['DATABASE_URL']),
        'provider': 'Neon' if host.endswith('.neon.tech') else 'unverified',
        'hostname_contains_pooler_marker': '-pooler' in host,
        'port': parsed.port or 5432,
        'connection_string_hidden': True,
    }
    url = api['DATABASE_URL']
    if '.railway.internal' in url:
        url = railway_json('variables', '--service', 'Postgres', '--environment', 'production')['DATABASE_PUBLIC_URL']
    engine = create_database_engine(url, connect_args={'timeout': 15})
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            await conn.execute(text("SET LOCAL statement_timeout='15s'"))
            data['migration'] = list((await conn.execute(text('SELECT version_num FROM alembic_version'))).scalars())
            columns = set((await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='recording_jobs'"))).scalars())
            data['admission_schema_present'] = {'admission_version','authorized_at','authorized_by','submission_count'} <= columns
            rows = (await conn.execute(text('SELECT id,status,attempts,max_attempts,updated_at FROM recording_jobs ORDER BY id'))).mappings().all()
            data['job_count'] = len(rows)
            data['job_status_attempts_fingerprint'] = hashlib.sha256(json.dumps([dict(row) for row in rows],default=str,sort_keys=True).encode()).hexdigest()
            data['protected_jobs'] = [dict(row) for row in rows if str(row['id']) in JOB_IDS]
            data['active_jobs'] = [dict(row) for row in rows if row['status'] in ('pending','processing')]
            if data['admission_schema_present']:
                data['admitted_count'] = await conn.scalar(text('SELECT count(*) FROM recording_jobs WHERE admission_version=1 AND authorized_at IS NOT NULL AND authorized_by IS NOT NULL'))
            else:
                data['admitted_count'] = None
            await conn.rollback()
    finally:
        await engine.dispose()
    status = railway_json('status', '--environment', 'production')
    data['deployment'] = []
    for env in status['environments']['edges']:
        for edge in env['node']['serviceInstances']['edges']:
            node = edge['node']
            if node['serviceName'] not in services:
                continue
            data['deployment'].append({
                'service': node['serviceName'], 'service_id': node.get('serviceId'),
                'start_command': node.get('startCommand'),
                'sleep_application': node.get('sleepApplication'),
                'active': [{key: dep.get(key) for key in ('id','status','deploymentStopped','createdAt')}
                           for dep in node.get('activeDeployments') or []],
            })
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        domain = api.get('RAILWAY_PUBLIC_DOMAIN')
        if not domain:
            for env in status['environments']['edges']:
                for edge in env['node']['serviceInstances']['edges']:
                    node = edge['node']
                    if node['serviceName'] == 'meeting-intel-api':
                        domains = (node.get('domains') or {}).get('serviceDomains') or []
                        if domains:
                            domain = domains[0]['domain']
        if domain:
            response = await client.get('https://' + domain + '/health')
            data['api_health_http'] = response.status_code
        try:
            response = await client.get('https://api.assemblyai.com/v2/transcript',
                params={'limit': 1}, headers={'authorization': api.get('ASSEMBLYAI_API_KEY','')})
            data['provider_read_only_check'] = {'method':'GET', 'http_status':response.status_code,
                'credentials_accepted_for_list': response.status_code == 200,
                'billing_balance_verified':False, 'transcript_content_saved':False,
                'upload_or_submit_requests':0}
        except httpx.HTTPError as exc:
            data['provider_read_only_check'] = {'error_type':type(exc).__name__, 'upload_or_submit_requests':0}
    DEST.mkdir(parents=True, exist_ok=True)
    path = DEST / ('preflight-' + datetime.now(timezone.utc).strftime('%H%M%S') + '.json')
    path.write_text(json.dumps(data, default=str, indent=2), encoding='utf-8')
    print(json.dumps(data, default=str))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__, 'details_suppressed':True}))
        sys.exit(1)
