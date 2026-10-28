"""Opt-in real PostgreSQL checks; never uses an environment database URL."""
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CONTAINER = "meeting-intel-acceptance-20261015"
BASELINE = "81c5f02a9d31"
HEAD = "51d8f2a7c903"
OWNER = "owner@example.test"

# These process-local settings precede all application imports. No .env is read.
for key, value in {
    "DATABASE_URL": "postgresql+asyncpg://offline:offline@127.0.0.1:1/offline_tests",
    "AUTH_MICROSOFT_ENTRA_ID_TENANT_ID": "offline-tenant",
    "AUTH_MICROSOFT_ENTRA_ID_ID": "offline-client",
    "AUTH_MICROSOFT_ENTRA_ID_SECRET": "offline-secret",
    "GRAPH_IMPL": "mock", "AUTH_MODE": "mock", "TRANSCRIBER_IMPL": "mock",
    "EXTRACTOR_IMPL": "transcript_only", "ASSEMBLYAI_API_KEY": "",
    "GEMINI_API_KEY": "", "GEMINI_ENABLED": "false", "AZURE_OPENAI_KEY": "",
    "EMAILS_ENABLED": "false", "AUTO_SEND_EMAIL": "false",
    "RECORDING_PROCESSING_ENABLED": "false", "ENABLE_AUTO_RECONCILE": "false",
}.items():
    os.environ[key] = value

from app import models
from app.api import reviews
from app.schemas import ApproveMeetingIn, MeetingDecisionsIn


class LocalTarget(tuple):
    """Keep generated connection credentials out of pytest fixture reprs."""

    def __repr__(self):
        return "LocalTarget(host=localhost, port=5435, credentials=hidden)"


def docker(*args, input=None):
    result = subprocess.run(["docker", *args], input=input, capture_output=True,
                            text=True, encoding="utf-8", timeout=45, check=False)
    if result.returncode:
        # Do not expose SQL, generated credentials or driver connection strings.
        raise RuntimeError("Local Docker test command failed; credentials/output suppressed")
    return result.stdout.strip()


@pytest.fixture(scope="session")
def target():
    if os.environ.get("MEETING_INTEL_TEST_PG_CONTAINER") != CONTAINER:
        pytest.skip("Explicit local Meeting Intel test-container opt-in required")
    endpoint = docker("context", "inspect", "--format", "{{json .Endpoints.docker.Host}}")
    assert endpoint.strip('"').startswith("npipe://")
    details = json.loads(docker("inspect", "--format", "{{json .}}", CONTAINER))
    assert details["Config"]["Image"] == "postgres:16"
    assert details["State"]["Running"]
    assert details["HostConfig"]["PortBindings"]["5432/tcp"] == [
        {"HostIp": "127.0.0.1", "HostPort": "5435"}]
    assert any(mount.get("Name") == CONTAINER + "-data" for mount in details["Mounts"])
    suffix = uuid4().hex[:12]
    database = "meeting_intel_decisions_pg_" + suffix
    role = "decisions_test_" + suffix
    password = secrets.token_hex(24)
    print(f"TEST TARGET host=localhost (127.0.0.1) port=5435 database={database}; "
          "evidence=Meeting-Intel acceptance container + named volume + postgres:16; credentials=hidden")

    def admin(sql):
        return docker("exec", "-i", CONTAINER, "psql", "-X", "-q", "-v",
                      "ON_ERROR_STOP=1", "-U", "postgres", "-d", "postgres", input=sql)

    created = False
    admin(f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;")
    try:
        admin(f"CREATE DATABASE {database} OWNER {role};")
        created = True
        admin(f"REVOKE ALL ON DATABASE {database} FROM PUBLIC;")
        url = f"postgresql+asyncpg://{role}:{password}@localhost:5435/{database}"

        def migrate(direction, revision):
            environment = dict(os.environ, DATABASE_URL=url)
            # Production engine requires TLS. Override transport only in this child
            # process after validating the generated loopback test URL.
            runner = """
import os, sys
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
import app.database
from alembic import command
from alembic.config import Config
url = make_url(os.environ['DATABASE_URL'])
assert url.host == 'localhost' and url.port == 5435
assert url.database.startswith('meeting_intel_decisions_pg_')
app.database.create_database_engine = lambda value, **options: create_async_engine(value, connect_args={'ssl': False}, **options)
getattr(command, sys.argv[1])(Config('alembic.ini'), sys.argv[2])
"""
            result = subprocess.run([sys.executable, "-B", "-c", runner, direction, revision],
                                    cwd=ROOT, env=environment, capture_output=True, text=True,
                                    encoding="utf-8", timeout=90, check=False)
            if result.returncode:
                safe = (result.stdout + result.stderr).replace(password, "[hidden]").replace(role, "[hidden]")
                raise RuntimeError("\n".join(safe.splitlines()[-12:]))
            print(f"alembic {direction} {revision}: PASS")

        migrate("upgrade", BASELINE)
        migrate("upgrade", HEAD)
        yield LocalTarget((url, migrate))
    finally:
        if created:
            assert database.startswith("meeting_intel_decisions_pg_")
            docker("exec", CONTAINER, "dropdb", "--force", "-U", "postgres", database)
        admin(f"DROP ROLE {role};")
        print("CLEANUP temporary test database and role removed; existing databases untouched")


@pytest.fixture(autouse=True)
def isolate_transports(monkeypatch):
    original = asyncio.BaseEventLoop.create_connection

    async def local_connection(loop, protocol_factory, host=None, port=None, **kwargs):
        assert host in {"localhost", "127.0.0.1"} and int(port) == 5435, "Only local test PostgreSQL is allowed"
        return await original(loop, protocol_factory, host, port, **kwargs)

    original_connect = socket.socket.connect

    def local_connect(sock, address):
        fallback = getattr(socket, "_fallback_socketpair", None)
        if fallback and sys._getframe(1).f_code is fallback.__code__:
            return original_connect(sock, address)
        assert address[0] == "127.0.0.1" and address[1] == 5435
        return original_connect(sock, address)

    monkeypatch.setattr(asyncio.BaseEventLoop, "create_connection", local_connection)
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(reviews.graph, "send_mail", AsyncMock(side_effect=AssertionError("No mail allowed")))


@pytest.fixture
async def sessions(target):
    engine = create_async_engine(target[0], echo=False, connect_args={"ssl": False})
    async with engine.connect() as connection:
        row = (await connection.execute(text(
            "SELECT current_database(), inet_server_port(), inet_server_addr()::text"))).one()
        assert row[0].startswith("meeting_intel_decisions_pg_") and row[1] == 5432
        assert row[2] is not None
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def seed(sessions, state=models.ProcessingState.awaiting_review):
    async with sessions() as db:
        meeting = models.Meeting(drive_item_id="synthetic-pg-" + uuid4().hex,
            title="[Synthetic Decisions PG]", organizer_upn=OWNER, state=state,
            summary="Legacy summary", transcript="Legacy transcript",
            extracted_json={"objective": "Legacy extraction"},
            approved_by=OWNER if state == models.ProcessingState.approved else None,
            approved_at=datetime(2026, 10, 22, tzinfo=UTC) if state == models.ProcessingState.approved else None,
            approved_recipients=[OWNER] if state == models.ProcessingState.approved else None)
        db.add(meeting)
        await db.flush()
        db.add(models.MeetingParticipant(meeting_id=meeting.id, user_upn=OWNER,
            is_organizer=True, access_type="participant", edit_access_status="approved"))
        db.add(models.ActionItem(meeting_id=meeting.id, task="Legacy completed task",
            confidence=models.Confidence.medium, approved=True,
            completed_at=datetime(2026, 10, 22, tzinfo=UTC)))
        await db.commit()
        return meeting.id


def body(content="Human decision", row_id=None):
    entry = {"content": content, "decision_date": "2026-10-28"}
    if row_id:
        entry["id"] = row_id
    return MeetingDecisionsIn(decisions=[entry])


async def save(sessions, meeting_id, payload=None, upn=OWNER):
    async with sessions() as db:
        return await reviews.save_meeting_decisions(meeting_id, payload or body(), Response(), db, upn)


async def snapshot(sessions):
    async with sessions() as db:
        result = {}
        for table in ("meetings", "meeting_participants", "action_items", "meeting_email_audits", "audit_events"):
            result[table] = (await db.execute(text(
                f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id), '[]'::jsonb)::text FROM {table} t"))).scalar_one()
        return result


async def test_full_migration_upgrade_rollback_reupgrade_preserves_legacy(target, sessions):
    target[1]("downgrade", BASELINE)
    meeting_id = await seed(sessions, models.ProcessingState.approved)
    async with sessions() as db:
        db.add(models.MeetingEmailAudit(meeting_id=meeting_id, actor_upn=OWNER,
            recipient_upn=OWNER, status="sent"))
        db.add(models.AuditEvent(event_type="synthetic.legacy.approved", outcome="succeeded",
            actor_type="system", actor_id="synthetic-test", resource_type="meeting",
            resource_id=meeting_id, meeting_id=meeting_id, correlation_id=uuid4(),
            event_key="synthetic-legacy-" + uuid4().hex, event_metadata={"fixture": True}))
        await db.commit()
    before = await snapshot(sessions)
    target[1]("upgrade", HEAD)
    assert await snapshot(sessions) == before
    async with sessions() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert await reviews.get_meeting_decisions(meeting_id, Response(), db, OWNER) == []
        db.add(models.MeetingDecision(meeting_id=meeting_id, content="Migration fixture", decision_date=date(2026, 10, 28)))
        await db.commit()
    target[1]("downgrade", BASELINE)
    assert await snapshot(sessions) == before
    async with sessions() as db:
        assert await db.scalar(text("SELECT to_regclass('public.meeting_decisions') IS NULL"))
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == BASELINE
    target[1]("upgrade", HEAD)
    assert await snapshot(sessions) == before
    async with sessions() as db:
        assert await db.scalar(text("SELECT count(*) FROM meeting_decisions")) == 0
        assert await db.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname='ix_meeting_decisions_meeting_id'")) == 1


async def test_create_update_delete_and_old_data(sessions):
    meeting_id = await seed(sessions)
    first = (await save(sessions, meeting_id))[0]
    second = (await save(sessions, meeting_id, body("Revised decision", first.id)))[0]
    assert second.id == first.id and second.content == "Revised decision"
    await save(sessions, meeting_id, MeetingDecisionsIn(decisions=[]))
    async with sessions() as db:
        assert await reviews.get_meeting_decisions(meeting_id, Response(), db, OWNER) == []
        meeting = await db.get(models.Meeting, meeting_id)
        assert meeting.summary == "Legacy summary" and meeting.transcript == "Legacy transcript"
        assert meeting.extracted_json["objective"] == "Legacy extraction"
        action = await db.scalar(select(models.ActionItem).where(models.ActionItem.meeting_id == meeting_id))
        assert action.approved and action.completed_at is not None


@pytest.mark.parametrize("access", ["request_view", "request_edit", "revoked", "outsider", "shared"])
async def test_permissions_and_search_isolation(sessions, access):
    meeting_id = await seed(sessions)
    await save(sessions, meeting_id, body("secret-pg-decision"))
    async with sessions() as db:
        meeting = await db.get(models.Meeting, meeting_id)
        meeting.state = models.ProcessingState.approved
        if access != "outsider":
            db.add(models.MeetingParticipant(meeting_id=meeting_id, user_upn="viewer@example.test",
                access_type=access, edit_access_status="none"))
        await db.commit()
    async with sessions() as db:
        if access == "shared":
            assert len(await reviews.get_meeting_decisions(meeting_id, Response(), db, "viewer@example.test")) == 1
        else:
            with pytest.raises(HTTPException) as failure:
                await reviews.get_meeting_decisions(meeting_id, Response(), db, "viewer@example.test")
            assert failure.value.status_code == 403
        rows = await reviews.search_meetings(response=Response(), db=db, upn="viewer@example.test", q="secret-pg-decision")
        assert bool(rows) == (access == "shared")
    with pytest.raises(HTTPException) as failure:
        await save(sessions, meeting_id, upn="viewer@example.test")
    assert failure.value.status_code == 403


async def test_duplicate_and_foreign_ids_leave_existing_decisions_unchanged(sessions):
    meeting_id = await seed(sessions)
    first = (await save(sessions, meeting_id))[0]
    other = await seed(sessions)
    foreign = (await save(sessions, other))[0]
    for ids in ([first.id, first.id], [foreign.id]):
        invalid = MeetingDecisionsIn(decisions=[{"id": identifier, "content": "Bad edit", "decision_date": "2026-10-28"} for identifier in ids])
        with pytest.raises(HTTPException) as failure:
            await save(sessions, meeting_id, invalid)
        assert failure.value.status_code == 422
    async with sessions() as db:
        rows = await reviews.get_meeting_decisions(meeting_id, Response(), db, OWNER)
        assert len(rows) == 1 and rows[0].content == "Human decision"


async def test_stale_preview_rejected_fresh_approval_locks_decisions(sessions):
    meeting_id = await seed(sessions)
    async with sessions() as db:
        old = await reviews.email_preview(meeting_id, db=db, upn=OWNER, recipients=[])
    await save(sessions, meeting_id)
    async with sessions() as db:
        with pytest.raises(HTTPException) as failure:
            await reviews.approve(meeting_id, db=db, upn=OWNER,
                body=ApproveMeetingIn(recipients=[], expected_fingerprint=old.fingerprint))
        assert failure.value.status_code == 409
    async with sessions() as db:
        fresh = await reviews.email_preview(meeting_id, db=db, upn=OWNER, recipients=[])
        result = await reviews.approve(meeting_id, db=db, upn=OWNER,
            body=ApproveMeetingIn(recipients=[], expected_fingerprint=fresh.fingerprint))
        assert result["state"] == models.ProcessingState.approved
    with pytest.raises(HTTPException) as failure:
        await save(sessions, meeting_id)
    assert failure.value.status_code == 409


async def wait_for_blocked(sessions):
    for _ in range(100):
        async with sessions() as db:
            blocked = await db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
            if blocked:
                return
        await asyncio.sleep(0.02)
    raise AssertionError("No real PostgreSQL lock wait observed")


async def test_concurrent_whole_list_saves_serialize(sessions):
    meeting_id = await seed(sessions)
    async with sessions() as first:
        # Hold the real parent row lock until the first endpoint commits.
        await reviews._authorize(first, meeting_id, OWNER, for_update=True)
        second = asyncio.create_task(save(sessions, meeting_id, body("Second draft")))
        try:
            await wait_for_blocked(sessions)
            assert not second.done()
            await reviews.save_meeting_decisions(meeting_id, body("First draft"), Response(), first, OWNER)
            await asyncio.wait_for(second, timeout=10)
        finally:
            if not second.done():
                second.cancel()
                await asyncio.gather(second, return_exceptions=True)
    async with sessions() as db:
        rows = await reviews.get_meeting_decisions(meeting_id, Response(), db, OWNER)
        assert len(rows) == 1 and rows[0].content == "Second draft"


async def test_approval_commit_rejects_blocked_save(sessions):
    meeting_id = await seed(sessions)
    async with sessions() as approver:
        await reviews._authorize(approver, meeting_id, OWNER, for_update=True)
        preview = await reviews.email_preview(meeting_id, db=approver, upn=OWNER, recipients=[])
        pending = asyncio.create_task(save(sessions, meeting_id))
        try:
            await wait_for_blocked(sessions)
            await reviews.approve(meeting_id, db=approver, upn=OWNER,
                body=ApproveMeetingIn(recipients=[], expected_fingerprint=preview.fingerprint))
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(pending, timeout=10)
            assert failure.value.status_code == 409
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    async with sessions() as db:
        assert await reviews.get_meeting_decisions(meeting_id, Response(), db, OWNER) == []


async def test_save_commit_invalidates_blocked_approval(sessions):
    meeting_id = await seed(sessions)
    async with sessions() as db:
        preview = await reviews.email_preview(meeting_id, db=db, upn=OWNER, recipients=[])
    async def approve():
        async with sessions() as db:
            return await reviews.approve(meeting_id, db=db, upn=OWNER,
                body=ApproveMeetingIn(recipients=[], expected_fingerprint=preview.fingerprint))
    async with sessions() as editor:
        await reviews._authorize(editor, meeting_id, OWNER, for_update=True)
        pending = asyncio.create_task(approve())
        try:
            await wait_for_blocked(sessions)
            await reviews.save_meeting_decisions(meeting_id, body(), Response(), editor, OWNER)
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(pending, timeout=10)
            assert failure.value.status_code == 409
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)



@pytest.mark.parametrize("state,expected", [
    (models.ProcessingState.awaiting_review, False),
    (models.ProcessingState.approved, True),
    (models.ProcessingState.sent, True),
])
async def test_decision_search_only_exposes_reviewed_decisions(sessions, state, expected):
    meeting_id = await seed(sessions)
    keyword = "search-state-" + uuid4().hex
    await save(sessions, meeting_id, body(keyword))
    async with sessions() as db:
        meeting = await db.get(models.Meeting, meeting_id)
        meeting.state = state
        await db.commit()
    async with sessions() as db:
        rows = await reviews.search_meetings(Response(), db, OWNER, keyword)
        assert bool(rows) == expected
        if expected:
            assert rows[0]["id"] == meeting_id and rows[0]["matched_decisions"]
