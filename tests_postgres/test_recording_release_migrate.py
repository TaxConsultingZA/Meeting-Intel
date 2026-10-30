"""Exercise the release runner only against the existing opt-in loopback fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys

from test_decisions import target  # noqa: F401


def test_bounded_release_runner_is_read_only_until_explicit_apply(target):
    environment = dict(os.environ, DATABASE_URL=target[0], RECORDING_PROCESSING_ENABLED='false',
        SERVICE_ROLE='api', EXTRACTOR_IMPL='transcript_only', EMAILS_ENABLED='false',
        AUTO_SEND_EMAIL='false', ENABLE_AUTO_RECONCILE='false')
    runner = '''
import os,sys,runpy
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
import app.database
url=make_url(os.environ['DATABASE_URL'])
assert url.host=='localhost' and url.port==5435 and url.database.startswith('meeting_intel_decisions_pg_')
def local(value,**options):
 args=options.pop('connect_args',{})
 assert args['server_settings']=={'lock_timeout':'5s','statement_timeout':'60s'}
 args['ssl']=False
 return create_async_engine(value,connect_args=args,**options)
app.database.create_database_engine=local
sys.argv=['scripts/recording_release_migrate.py',*sys.argv[1:]]
runpy.run_path('scripts/recording_release_migrate.py',run_name='__main__')
'''
    def run(*args):
        result = subprocess.run([sys.executable,'-c',runner,*args],cwd=Path(__file__).resolve().parents[1],
            env=environment,capture_output=True,text=True,timeout=90)
        return result.returncode, json.loads(result.stdout.splitlines()[-1])
    code, state = run()
    assert code == 0 and state['revisions'] == ['51d8f2a7c903'] and state['read_only']
    assert run('--apply')[0] != 0
    assert run()[1]['revisions'] == ['51d8f2a7c903']
    environment['RECORDING_PROCESSING_ENABLED'] = 'true'
    assert run('--apply','--backup-reference','synthetic','--restore-verified')[0] != 0
    assert run()[1]['revisions'] == ['51d8f2a7c903']
    environment['RECORDING_PROCESSING_ENABLED'] = 'false'
    code, state = run('--apply','--backup-reference','synthetic-local-fixture','--restore-verified')
    assert code == 0 and state['migrated_to'] == '92d6a10f4e72'
    assert run()[1]['revisions'] == ['92d6a10f4e72']
