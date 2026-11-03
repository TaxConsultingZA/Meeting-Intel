"""Isolated PostgreSQL + real HTTP acceptance fixture. Never import app.main/workers.
Use --prepare to create a new disposable database and verify races; --serve for UI.
Only localhost:55483 and the explicitly created embedded cluster are accepted.
"""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
from uuid import uuid4
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts/meeting-insights"
FIXTURE = OUT / "release-fixtures.json"
HOST, PORT = "127.0.0.1", 55483
# Guard even accidental provider calls; no DNS/external connections in this process.
_original_connect = socket.socket.connect
_original_resolve = socket.getaddrinfo
def safe_connect(sock, address):
    if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
        return _original_connect(sock, address)
    raise AssertionError("External network forbidden in insights acceptance")
def safe_resolve(host, *args, **kwargs):
    if host not in ("127.0.0.1", "::1", "localhost", None):
        raise AssertionError("External DNS forbidden in insights acceptance")
    return _original_resolve(host, *args, **kwargs)
socket.socket.connect = safe_connect
socket.getaddrinfo = safe_resolve

prepare = "--prepare" in sys.argv
metadata = {"database": "meeting_insights_" + uuid4().hex[:12]} if prepare else json.loads(FIXTURE.read_text(encoding="utf-8"))
name = metadata["database"]
assert name.startswith("meeting_insights_") and name.replace("_", "").isalnum()
url = f"postgresql+asyncpg://postgres@127.0.0.1:{PORT}/{name}"
from app import config
from app import database as local_database
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url
def local_engine(value, **options):
    parsed = make_url(value)
    assert parsed.host == HOST and parsed.port == PORT and parsed.database == name
    options["connect_args"] = {"ssl": False}
    return create_async_engine(value, **options)
local_database.create_database_engine = local_engine
# _env_file=None: never load shared environment files or existing credentials.
settings = config.Settings(_env_file=None, tenant_id="synthetic", client_id="synthetic", client_secret="synthetic", database_url=url,
    auth_mode="mock", graph_impl="mock", allowed_domain="example.test", emails_enabled=False,
    auto_send_email=False, enable_auto_reconcile=False)
config.get_settings = lambda: settings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import Base, get_db
from app.models import Meeting, MeetingParticipant, RegisteredUser, ActionItem, MeetingInsightDraft, ProcessingState
from app.api import reviews, meeting_insights, action_items, recording_jobs, notifications
from app.services import meeting_insights as service
engine = create_async_engine(url, connect_args={"server_settings": {"application_name": "insights_local_validation", "statement_timeout": "15000"}})
sessions = async_sessionmaker(engine, expire_on_commit=False)
async def database():
    async with sessions() as db:
        yield db
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8975"], allow_headers=["*"], allow_methods=["GET", "POST", "PUT"])
app.dependency_overrides[get_db] = database
for router in (reviews.router, meeting_insights.router, action_items.router, recording_jobs.router, notifications.router):
    app.include_router(router)
requests = []
@app.middleware("http")
async def allow_only_fixture_routes(request: Request, call_next):
    path, method = request.url.path, request.method
    safe = method == "OPTIONS" or (method == "GET" and (path.startswith("/reviews/") or path in ("/action-items", "/recordings/jobs", "/notifications"))) or (method in ("PUT", "POST") and path.endswith("/insights")) or (method == "PUT" and path.startswith("/action-items/") and path.endswith("/completion"))
    if not safe:
        return JSONResponse({"detail": "Not available in offline acceptance"}, status_code=403)
    response = await call_next(request)
    requests.append({"method": method, "path": path, "status": response.status_code})
    (OUT / "release-api-requests.json").write_text(json.dumps(requests, indent=2), encoding="utf-8")
    return response

async def seed(db, label):
    owner, editor, viewer = [f"{role}@example.test" for role in ("owner", "editor", "viewer")]
    m = Meeting(drive_item_id="synthetic-" + uuid4().hex, title="SYNTHETIC DATA ONLY - " + label + " " + uuid4().hex[:8],
        organizer_upn=owner, state=ProcessingState.awaiting_review, summary="Saved original notes - synthetic only",
        transcript="[Speaker A] We will prepare a synthetic demo.\n[Speaker B] Please prepare the synthetic evidence.\n[Speaker A] Please review the synthetic checklist.\n[Speaker B] We decided to review locally.\n[Speaker A] We agreed to use mock data.",
        attendees_raw=[owner, editor], extracted_json={"synthetic_only": True})
    db.add(m); await db.flush()
    for upn, access, edit in [(owner,"participant","none"),(editor,"participant","approved"),(viewer,"shared","none")]:
        db.add(MeetingParticipant(meeting_id=m.id, user_upn=upn, access_type=access, edit_access_status=edit))
    await db.commit()
    return m.id

async def verify():
    import asyncpg
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from httpx import AsyncClient, ASGITransport
    admin = await asyncpg.connect(host=HOST, port=PORT, user="postgres", database="postgres")
    directory = Path(await admin.fetchval("show data_directory")).resolve()
    assert directory == (OUT / "pg-data").resolve(), "Not the isolated embedded cluster"
    await admin.execute('CREATE DATABASE "' + name + '"')
    await admin.close()
    results = []
    def passed(label, **details):
        results.append({"check": label, "result": "passed", **details}); print("PASS", label)
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    async def migrate(direction, revision):
        await asyncio.to_thread(getattr(command, direction), cfg, revision)
    await migrate("upgrade", "92d6a10f4e72")
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == "92d6a10f4e72"
    passed("Full migration chain reaches actual deployment head 92d6a10f4e72")
    async with sessions() as db:
        for role in ("owner", "editor", "viewer", "outsider"):
            db.add(RegisteredUser(upn=f"{role}@example.test", display_name="Synthetic " + role, is_admin=False))
        await db.commit()
        legacy_id = await seed(db, "migration preservation")
        db.add(ActionItem(meeting_id=legacy_id,task="Synthetic legacy action retained",approved=False,source_quote="Synthetic old evidence")); await db.commit()
    async def snapshot(conn):
        return await conn.scalar(text("SELECT jsonb_build_object('meetings',(SELECT jsonb_agg(to_jsonb(m) ORDER BY id) FROM meetings m),'participants',(SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM meeting_participants p),'actions',(SELECT jsonb_agg(to_jsonb(a) ORDER BY id) FROM action_items a))::text"))
    async with engine.connect() as conn:
        before = await snapshot(conn)
    await migrate("upgrade", "62e9a3b8d014")
    async with engine.begin() as conn:
        assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == "62e9a3b8d014"
        assert before == await snapshot(conn)
        await conn.execute(text("INSERT INTO meeting_insight_drafts VALUES (:mid,1,'awaiting_review','synthetic-hash',:payload,NULL)"),
            {"mid": legacy_id, "payload": '{"summary":"synthetic","actions":[],"decisions":[]}'})
    await migrate("downgrade", "92d6a10f4e72")
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == "92d6a10f4e72"
        assert await conn.scalar(text("select to_regclass('meeting_insight_drafts')")) is None
        assert before == await snapshot(conn)
    await migrate("upgrade", "head")
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == "62e9a3b8d014"
        passed("Alembic target-head upgrade/downgrade/upgrade preserves saved data", version=await conn.scalar(text("show server_version")))
    async with sessions() as db:
        race_id = await seed(db, "concurrency")
        ui_id = await seed(db, "page flow")
        fail_id = await seed(db, "failure retry")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://offline") as client:
        async def call(method, path, actor="owner", body=None):
            return await client.request(method, path, headers={"Authorization":f"Bearer mock:{actor}@example.test"}, json=body)
        endpoint = f"/reviews/{race_id}/insights"
        original = service.adapter
        class CountingAdapter:
            calls = 0
            async def analyze(self, transcript):
                self.calls += 1
                await asyncio.sleep(.2)
                return await original.analyze(transcript)
        counted = CountingAdapter(); service.adapter = counted
        a,b = await asyncio.gather(call("POST",endpoint),call("POST",endpoint,"editor"))
        service.adapter = original
        assert a.status_code == b.status_code == 200 and a.json() == b.json() and counted.calls == 1
        passed("Two authorized users concurrently generate exactly one draft", adapter_calls=counted.calls)
        body = a.json(); body["summary"] = "Human revised synthetic notes"; body["actions"][0]["status"] = "confirmed"; body["actions"][0]["owner"] = "owner@example.test"; body["actions"][0]["deadline"] = "2026-11-03"
        body["actions"][1]["status"] = "rejected"
        # Third candidate remains pending and must not enter Action Items.
        a,b = await asyncio.gather(call("PUT",endpoint,body=body),call("PUT",endpoint,"editor",body))
        assert sorted([a.status_code,b.status_code]) == [200,409]
        passed("Concurrent confirmation commits once and rejects stale second reviewer", statuses=sorted([a.status_code,b.status_code]))
        assert (await call("PUT",endpoint,body=body)).status_code == 409
        current=(await call("GET",endpoint)).json()
        assert current["version"] == 2 and current["summary"] == body["summary"]
        assert (await call("POST",endpoint)).json() == current
        passed("Duplicate confirmation and repeated generate preserve human edits")
        # Two real connections: hold parent lock, observe wait, release it.
        async with sessions() as lock_db:
            await lock_db.scalar(select(Meeting).where(Meeting.id == race_id).with_for_update())
            task = asyncio.create_task(call("PUT", endpoint, "editor", current))
            await asyncio.sleep(.25)
            assert not task.done()
            async with sessions() as monitor:
                waiters = await monitor.scalar(text("select count(*) from pg_stat_activity where datname=current_database() and wait_event_type='Lock'"))
            assert waiters >= 1
            await lock_db.commit()
            response = await asyncio.wait_for(task, 5)
            assert response.status_code == 200
            passed("Competing review waits for real PostgreSQL row lock and resumes", observed_lock_waiters=waiters)
        # Explicit short timeout on a separate competing connection must rollback safely.
        async with sessions() as lock_db:
            await lock_db.scalar(select(Meeting).where(Meeting.id == race_id).with_for_update())
            async with sessions() as waiting:
                await waiting.execute(text("SET LOCAL lock_timeout = '100ms'"))
                try:
                    await waiting.scalar(select(Meeting).where(Meeting.id == race_id).with_for_update())
                    raise AssertionError("Expected lock timeout")
                except Exception as exc:
                    assert "lock timeout" in str(exc).lower()
                    await waiting.rollback()
            await lock_db.rollback()
        passed("PostgreSQL lock timeout rolls back competing transaction")
        rows=(await call("GET","/action-items?view=all")).json()["items"]
        assert len(rows)==1 and rows[0]["confirmation_source"]=="insight_review" and not rows[0]["meeting_notes_approved"] and rows[0]["can_complete"]
        assert rows[0]["deadline_iso"] == "2026-11-03"
        aid=rows[0]["id"]
        assert (await call("PUT",f"/action-items/{aid}/completion",body={"completed":True})).status_code==200
        assert (await call("PUT",f"/action-items/{aid}/completion",body={"completed":False})).status_code==200
        viewer=(await call("GET","/action-items?view=all","viewer")).json()["items"]
        assert len(viewer)==1 and not viewer[0]["can_complete"]
        assert (await call("PUT",f"/action-items/{aid}/completion","viewer",{"completed":True})).status_code==403
        assert (await call("GET","/action-items?view=all","outsider")).json()["items"]==[]
        passed("Only confirmed candidate is visible; task complete/reopen respects original permissions")
        class FailingAdapter:
            async def analyze(self, transcript): raise TimeoutError("synthetic timeout")
        service.adapter=FailingAdapter()
        fail_url=f"/reviews/{fail_id}/insights"
        assert (await call("POST",fail_url)).json()["status"]=="failed"
        service.adapter=original
        assert (await call("POST",fail_url)).json()["status"]=="awaiting_review"
        passed("Analysis timeout preserves transcript and supports safe retry")
    async with sessions() as db:
        m=await db.get(Meeting,race_id)
        assert m.state==ProcessingState.awaiting_review and m.approved_at is None and m.approved_by is None
        assert m.summary=="Saved original notes - synthetic only" and m.transcript.startswith("[Speaker A]")
        assert m.email_delivery_status is None
        passed("Confirmation and task management never approve notes or queue email")
    async with sessions() as db:
        ui_title=(await db.get(Meeting,ui_id)).title
    metadata.update({"ui_title":ui_title,"ui_id":str(ui_id), "race_id":str(race_id), "today":"2026-11-03","owner":"owner@example.test","editor":"editor@example.test","viewer":"viewer@example.test"})
    FIXTURE.write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    (OUT/"release-postgres-results.json").write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding="utf-8")
    await engine.dispose()

if __name__ == "__main__":
    if prepare: asyncio.run(verify())
    elif "--new-ui" in sys.argv:
        async def new_ui():
            async with sessions() as db:
                mid = await seed(db, "page flow")
                metadata["ui_id"] = str(mid)
                metadata["ui_title"] = (await db.get(Meeting,mid)).title
            FIXTURE.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            await engine.dispose()
        asyncio.run(new_ui())
    elif "--serve" in sys.argv:
        import uvicorn
        uvicorn.run(app,host="127.0.0.1",port=8976,log_level="warning")
