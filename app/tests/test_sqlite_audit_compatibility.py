"""Test-only SQLite adapters preserve the production audit schema/default."""
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.models import AuditEvent, Base


def test_sqlite_schema_and_audit_server_default():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            # Raw SQL deliberately bypasses the Python default=dict so this
            # exercises the actual SQLite server default for omitted metadata.
            connection.execute(text("""INSERT INTO audit_events (
                id, event_type, outcome, actor_type, actor_id, resource_type,
                resource_id, correlation_id, event_key
            ) VALUES (
                :id, 'recording.retry', 'requested', 'system', 'test',
                'recording_job', :resource_id, :correlation_id, 'sqlite-default'
            )"""), {
                "id": uuid4().hex,
                "resource_id": uuid4().hex,
                "correlation_id": uuid4().hex,
            })
            metadata, occurred_at = connection.execute(select(
                AuditEvent.event_metadata, AuditEvent.occurred_at,
            )).one()
            assert metadata == {}
            assert occurred_at is not None
    finally:
        engine.dispose()


def test_sqlite_compilation_leaves_postgresql_audit_default_unchanged():
    table = AuditEvent.__table__
    before = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    sqlite_ddl = str(CreateTable(table).compile(dialect=sqlite.dialect()))
    after = str(CreateTable(table).compile(dialect=postgresql.dialect()))

    assert "metadata JSON DEFAULT '{}' NOT NULL" in sqlite_ddl
    assert "metadata JSONB DEFAULT '{}'::jsonb NOT NULL" in before
    assert after == before
    assert table.c.metadata.server_default.arg.text == "'{}'::jsonb"


def test_sqlite_adapter_preserves_unrelated_text_compilation():
    statement = text("SELECT :value AS value").bindparams(value=7)
    assert str(statement.compile(
        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True},
    )) == "SELECT 7 AS value"
    # An equal string is not the audit default object and must pass through.
    assert str(text("'{}'::jsonb").compile(dialect=sqlite.dialect())) == "'{}'::jsonb"
