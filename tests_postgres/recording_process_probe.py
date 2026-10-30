"""Child-process probe; only disposable loopback PostgreSQL, no HTTP transports."""
import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main():
    payload = json.loads(sys.stdin.readline())
    from sqlalchemy.engine import make_url
    url = make_url(payload['url'])
    assert url.host == 'localhost' and url.port == 5435
    assert url.database.startswith('meeting_intel_decisions_pg_')
    os.environ.update(DATABASE_URL=payload['url'], GRAPH_IMPL='mock', AUTH_MODE='mock',
        TRANSCRIBER_IMPL='mock', EXTRACTOR_IMPL='transcript_only', EMAILS_ENABLED='false',
        ASSEMBLYAI_API_KEY='', RECORDING_PROCESSING_ENABLED='false')
    original = socket.socket.connect
    def local_only(sock, address):
        assert address[0] in {'127.0.0.1', '::1'} and address[1] == 5435
        return original(sock, address)
    socket.socket.connect = local_only
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.queue import worker
    from app.services import transcription_submission as submission
    engine = create_async_engine(payload['url'], connect_args={'ssl': False})
    worker.engine = engine
    worker.SessionLocal = submission.SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    worker.settings.process_only_job_id = payload['job']
    try:
        if payload['operation'] == 'claim':
            row = await worker._claim_next()
            print(json.dumps({'claimed': row is not None, 'token': str(row.lease_token) if row else None}))
        elif payload['operation'] == 'reserve':
            try:
                await submission.checkpoint(UUID(payload['job']), UUID(payload['token']), reserve=True)
                print('{"reserved":true}')
            except RuntimeError:
                print('{"reserved":false}')
        elif payload['operation'] == 'hold':
            async with worker._recording_lock(payload['item']):
                print('{"holding":true}', flush=True)
                await asyncio.sleep(300)
        else:
            await worker._recover_interrupted_jobs()
            print('{"recovered":true}')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except BaseException as exc:
        print(json.dumps({'error_type': type(exc).__name__}))
        sys.exit(1)
