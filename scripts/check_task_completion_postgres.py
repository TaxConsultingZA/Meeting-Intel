"""Opt-in completion/migration check in a disposable schema of local acceptance.

Requires ACCEPTANCE_DATABASE_URL for localhost:5435/meeting_intel_acceptance.
Never uses the shared DATABASE_URL or existing acceptance records.
"""
import asyncio
import json
import os
from urllib.parse import urlparse
from uuid import uuid4


async def main():
    raw_url = os.environ.get("ACCEPTANCE_DATABASE_URL", "")
    parsed = urlparse(raw_url)
    if parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port != 5435 or parsed.path != "/meeting_intel_acceptance" or parsed.query:
        raise RuntimeError("Requires the verified isolated local acceptance database")
    os.environ["DATABASE_URL"] = raw_url
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from fastapi import Response
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.api.action_items import set_task_completion
    from app.db import Base
    from app.models import ActionItem, BusinessUnit, Meeting, MeetingParticipant, ProcessingState, RegisteredUser

    schema = "completion_test_" + uuid4().hex
    engine = create_async_engine(raw_url.replace("postgresql://", "postgresql+asyncpg://", 1),
                                 connect_args={"server_settings": {"search_path": schema}})
    # The installed Alembic package owns its namespace, so load our revision by path.
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    spec = spec_from_file_location("completion_revision", Path(__file__).resolve().parents[1] / "alembic/versions/2f7b9c1d4e60_add_task_completion.py")
    migration = module_from_spec(spec); spec.loader.exec_module(migration)

    def migrate(connection, direction):
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, direction)()

    try:
        async with engine.begin() as connection:
            assert await connection.scalar(text("select current_database()")) == "meeting_intel_acceptance"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[
                BusinessUnit.__table__, RegisteredUser.__table__, Meeting.__table__, MeetingParticipant.__table__, ActionItem.__table__]))
            await connection.run_sync(migrate, "downgrade")
            # Populate the previous schema before applying the additive upgrade.
            uid, mid, aid = uuid4(), uuid4(), uuid4()
            await connection.execute(RegisteredUser.__table__.insert().values(id=uid, upn="completion@example.invalid", is_admin=False))
            await connection.execute(Meeting.__table__.insert().values(id=mid, drive_item_id="meeting-intel-test-completion-concurrency", organizer_upn="completion@example.invalid", state=ProcessingState.approved, summary="Preserved notes"))
            await connection.execute(MeetingParticipant.__table__.insert().values(id=uuid4(), meeting_id=mid, user_upn="completion@example.invalid", access_type="participant", is_organizer=True))
            await connection.execute(ActionItem.__table__.insert().values(id=aid, meeting_id=mid, task="Preserved wording", confidence="high", approved=True))
            before = await connection.scalar(text("SELECT md5(to_jsonb(a)::text) FROM action_items a"))
            await connection.run_sync(migrate, "upgrade")
            after = await connection.scalar(text("SELECT md5((to_jsonb(a)-'completed_at'-'completed_by_id')::text) FROM action_items a"))
            assert before == after
            assert await connection.scalar(text("SELECT count(*) FROM action_items WHERE completed_at IS NULL AND completed_by_id IS NULL")) == 1
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        from app.schemas import TaskCompletionIn

        async def change(completed):
            async with sessions() as session:
                user = await session.get(RegisteredUser, uid)
                return await set_task_completion(aid, TaskCompletionIn(completed=completed), Response(), session, user)

        first, second = await asyncio.gather(change(True), change(True))
        assert first.completed_at == second.completed_at and first.completed_by_id == second.completed_by_id == uid
        assert first.completed_at.tzinfo is not None
        # Hold the established parent lock, then prove a competing reopen waits.
        async with sessions() as session:
            await session.scalar(select(Meeting).where(Meeting.id == mid).with_for_update())
            reopening = asyncio.create_task(change(False))
            await asyncio.sleep(0.15)
            assert not reopening.done()
            await session.commit()
            assert (await reopening).completed_at is None
        async with sessions() as session:
            item = await session.get(ActionItem, aid)
            meeting = await session.get(Meeting, mid)
            assert item.completed_at is None and item.completed_by_id is None
            assert item.task == "Preserved wording" and item.approved and meeting.summary == "Preserved notes" and meeting.state == ProcessingState.approved
        print(json.dumps({"migration_preserved_task": True, "existing_task_starts_open": True,
                          "concurrent_complete_idempotent": True, "reopen_waited_for_lock": True,
                          "persistence_and_notes_preserved": True}))
    finally:
        # Only this generated schema is disposable; public acceptance data stays intact.
        if not schema.startswith("completion_test_") or len(schema) != 48:
            raise RuntimeError("Unexpected disposable schema")
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
