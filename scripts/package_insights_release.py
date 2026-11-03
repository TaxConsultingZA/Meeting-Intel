"""Export explicit production-only files; never exports tests, local credentials or data."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    base = Path(tempfile.mkdtemp(prefix='meeting-intel-release-artifacts-'))
    api, frontend = base / 'api', base / 'frontend'
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    manifest = {'commit': commit, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'api_directory': str(api), 'frontend_directory': str(frontend), 'files': []}
    api_root = {'Dockerfile', '.dockerignore', 'requirements.txt', 'alembic.ini', 'scripts/check_insights_release.py'}
    front_root = {'package.json', 'package-lock.json', 'next.config.ts', 'tsconfig.json',
        'next-env.d.ts', 'postcss.config.mjs', '.vercelignore'}
    banned = (b'synthetic-insights-local-session-only', b'offline-secret',
              b'postgres@localhost:55483', b'mock:owner@example.test')
    for name in files:
        if not name:
            continue
        parts = Path(name).parts
        if any(part in {'__pycache__', 'node_modules', '.next', '__tests__', 'test', 'tests', 'fixtures', 'artifacts'} for part in parts):
            continue
        if any(part.startswith('.env') for part in parts) or name.endswith(('.log', '.pid', '.pyc', '.test.ts', '.test.tsx', '.spec.ts')):
            continue
        destination = None
        if name in api_root or name.startswith(('app/', 'alembic/')):
            destination = api / name
        elif name.startswith('frontend/'):
            relative = name[len('frontend/'):]
            if relative in front_root or relative.startswith(('src/', 'public/')):
                destination = frontend / relative
        if destination is None:
            continue
        data = (ROOT / name).read_bytes()
        assert not any(value in data for value in banned), 'Synthetic credential in production file: ' + name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        manifest['files'].append({'source': name, 'sha256': hashlib.sha256(data).hexdigest()})
    assert (api / 'alembic/versions/62e9a3b8d014_meeting_insight_drafts.py').is_file()
    assert (frontend / 'src/app/meetings/[id]/meeting-insights.tsx').is_file()
    assert (frontend / 'src/app/admin/audit-logs/audit-logs-client.tsx').is_file()
    for folder in (api, frontend):
        (folder / '.release-source.json').write_text(json.dumps({'commit': commit}) + '\n', encoding='utf-8')
    output = ROOT / 'artifacts/insights-release-execution'
    output.mkdir(parents=True, exist_ok=True)
    manifest['excluded'] = ['tests', 'fixtures', 'artifacts', 'PG data/backups', 'logs', '.env*', 'node_modules', '.next', 'local acceptance scripts']
    (output / 'package.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'commit': commit, 'file_count': len(manifest['files']), 'artifact_directories': [str(api), str(frontend)], 'sensitive_files_excluded': True}))


if __name__ == '__main__':
    main()
