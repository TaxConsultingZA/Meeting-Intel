"""Opt-in migration check in a disposable DB on Meeting Intel's local Docker PG."""
import importlib.util
import io
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_mock_engine

from app.db import Base
from app.models import MeetingDecision


def test_decision_migration_postgres_preserves_review_data():
    container = os.environ.get("MEETING_INTEL_TEST_PG_CONTAINER")
    if not container:
        pytest.skip("Set MEETING_INTEL_TEST_PG_CONTAINER to the existing local Meeting Intel PG container")
    assert container == "meeting-intel-acceptance-20261015"

    def command(*args, input=None):
        return subprocess.run(["docker", *args], input=input, capture_output=True,
                              text=True, encoding="utf-8", check=True, timeout=30).stdout.strip()

    host = command("context", "inspect", "--format", "{{json .Endpoints.docker.Host}}")
    assert host.strip('"').startswith(("npipe://", "unix://")), "Only local Docker contexts are allowed"
    assert command("inspect", "--format", "{{.Config.Image}}", container) == "postgres:16"
    database = "meeting_intel_decisions_v1_" + uuid4().hex[:8]

    def sql(statement):
        return command("exec", "-i", container, "psql", "-X", "-q", "-A", "-t", "-v",
                       "ON_ERROR_STOP=1", "-U", "postgres", "-d", database, input=statement)

    path = Path(__file__).parents[2] / "alembic/versions/51d8f2a7c903_add_meeting_decisions.py"
    spec = importlib.util.spec_from_file_location("decision_pg_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "81c5f02a9d31"

    def migration_sql(operation):
        output = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output})
        with Operations.context(context):
            operation()
        return output.getvalue()

    ddl = []
    engine = create_mock_engine("postgresql://", lambda statement, *a, **kw:
        ddl.append(str(statement.compile(dialect=engine.dialect)) + ";"))
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables
                                            if table is not MeetingDecision.__table__])
    snapshot = """SELECT jsonb_build_object(
        'meetings', (SELECT jsonb_agg(to_jsonb(m) ORDER BY id) FROM meetings m),
        'participants', (SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM meeting_participants p),
        'actions', (SELECT jsonb_agg(to_jsonb(a) ORDER BY id) FROM action_items a))::text;"""
    command("exec", container, "createdb", "-U", "postgres", database)
    try:
        sql("\n".join(ddl))
        sql("""
            INSERT INTO meetings (id, drive_item_id, state, summary, transcript, extracted_json,
                approved_by, approved_at, approved_recipients, email_delivery_attempts, created_at)
            VALUES ('00000000-0000-0000-0000-000000000001', 'synthetic-decision-migration',
                'approved', 'Legacy notes', 'Legacy transcript', '{"objective":"Legacy extraction"}',
                'owner@example.test', '2026-10-22T00:00:00Z', '["owner@example.test"]', 0, now());
            INSERT INTO meeting_participants (id, meeting_id, user_upn, is_organizer, access_type, edit_access_status)
            VALUES ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001',
                'owner@example.test', true, 'participant', 'approved');
            INSERT INTO action_items (id, meeting_id, task, confidence, approved)
            VALUES ('00000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001',
                'Legacy approved action', 'medium', true);
        """)
        before = sql(snapshot)
        sql(migration_sql(migration.upgrade))
        assert sql(snapshot) == before
        sql("""INSERT INTO meeting_decisions (id, meeting_id, content, decision_date)
            VALUES ('00000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001',
                'Human decision', '2026-10-23');""")
        assert sql("SELECT count(*) FROM meeting_decisions;") == "1"
        assert sql("SELECT count(*) FROM pg_indexes WHERE indexname='ix_meeting_decisions_meeting_id';") == "1"
        sql(migration_sql(migration.downgrade))
        assert sql("SELECT to_regclass('public.meeting_decisions') IS NULL;") == "t"
        assert sql(snapshot) == before
        print("PostgreSQL", sql("SHOW server_version;"), "upgrade/downgrade preserved meeting, approval, participant and action data")
    finally:
        command("exec", container, "dropdb", "-U", "postgres", database)
