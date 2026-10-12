"""Exercise audit ordering and real transactional persistence without network I/O."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ai.contracts import FailureCode
from app.ai.runtime_bridge import FoundationExtractionError
from app.models import AuditEvent
from app.services.ai_audit import audited_extraction
from app.services.job_control import guarded_commit, JobCancelled


@pytest.fixture
def audit_db():
    engine = create_engine("sqlite://")
    AuditEvent.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def types(db):
    return [e.event_type for e in db.scalars(select(AuditEvent).order_by(AuditEvent.event_type))]


async def invoke(db, extract, *, commit=None, meeting_id=None, job_id=None, lease_token=None):
    async def save():
        db.commit()
    return await audited_extraction(
        db, meeting_id=meeting_id or uuid4(), job_id=job_id, lease_token=lease_token,
        commit=commit or save, extract=extract, segments=["SECRET transcript"],
        implementation="mock",
    )


async def test_request_is_durable_before_call_and_success_is_content_free(audit_db):
    db = audit_db
    meeting_id, job_id, token = uuid4(), uuid4(), uuid4()

    async def extract(*args, **kwargs):
        assert types(db) == ["ai.extraction_requested"]
        return "SECRET AI response"

    assert await invoke(db, extract, meeting_id=meeting_id, job_id=job_id,
                        lease_token=token) == "SECRET AI response"
    rows = list(db.scalars(select(AuditEvent)))
    assert {r.event_type for r in rows} == {"ai.extraction_requested", "ai.extraction_completed"}
    assert {r.outcome for r in rows} == {"requested", "succeeded"}
    assert all(r.meeting_id == meeting_id and r.job_id == r.correlation_id == job_id for r in rows)
    assert all(r.actor_type == "system" and r.actor_id == "recording_worker" for r in rows)
    assert all(r.event_metadata == {} and str(token) not in r.event_key for r in rows)
    assert "SECRET" not in str([r.event_metadata for r in rows])


@pytest.mark.parametrize("failure,category", [
    (FoundationExtractionError(FailureCode.INVALID_OUTPUT), "invalid_output"),
    (RuntimeError("SECRET credentials, prompts, recipients"), "unknown"),
])
async def test_failure_persists_safe_category_and_reraises(audit_db, failure, category):
    with pytest.raises(type(failure)) as raised:
        await invoke(audit_db, AsyncMock(side_effect=failure))
    assert raised.value is failure
    assert types(audit_db) == ["ai.extraction_failed", "ai.extraction_requested"]
    failed = audit_db.scalars(select(AuditEvent).where(AuditEvent.outcome == "failed")).one()
    assert failed.event_metadata == {"error_category": category}


@pytest.mark.parametrize("failure", [asyncio.CancelledError(), JobCancelled("lease lost")])
async def test_cancellation_is_not_a_failure_or_completion(audit_db, failure):
    with pytest.raises(type(failure)):
        await invoke(audit_db, AsyncMock(side_effect=failure))
    assert types(audit_db) == ["ai.extraction_requested"]


async def test_retry_uses_distinct_attempt_keys(audit_db):
    meeting_id, job_id = uuid4(), uuid4()
    with pytest.raises(RuntimeError):
        await invoke(audit_db, AsyncMock(side_effect=RuntimeError()),
                     meeting_id=meeting_id, job_id=job_id, lease_token=uuid4())
    await invoke(audit_db, AsyncMock(return_value=object()),
                 meeting_id=meeting_id, job_id=job_id, lease_token=uuid4())
    rows = list(audit_db.scalars(select(AuditEvent)))
    assert len(rows) == 4 and len({r.event_key for r in rows}) == 4


async def test_request_commit_failure_prevents_provider_call(audit_db):
    extract = AsyncMock()

    async def fail():
        audit_db.rollback()
        raise RuntimeError("commit failed")

    with pytest.raises(RuntimeError):
        await invoke(audit_db, extract, commit=fail)
    extract.assert_not_awaited()
    assert types(audit_db) == []


@pytest.mark.parametrize("provider_fails", [False, True])
async def test_lost_lease_rolls_back_terminal_audit(audit_db, provider_fails):
    calls = 0

    async def fence():
        nonlocal calls
        calls += 1
        if calls == 2:
            audit_db.rollback()
            raise JobCancelled("lease lost")
        audit_db.commit()

    extract = AsyncMock(side_effect=RuntimeError("SECRET")) if provider_fails else AsyncMock(return_value=object())
    with pytest.raises(JobCancelled):
        await invoke(audit_db, extract, commit=fence, job_id=uuid4(), lease_token=uuid4())
    assert types(audit_db) == ["ai.extraction_requested"]


async def test_actual_guard_fences_audit_before_provider():
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    db.rollback = AsyncMock()
    db.commit = AsyncMock()
    extract = AsyncMock()
    job_id, token = uuid4(), uuid4()

    async def fence():
        await guarded_commit(db, job_id, token)

    with pytest.raises(JobCancelled):
        await invoke(db, extract, commit=fence, job_id=job_id, lease_token=token)
    extract.assert_not_awaited()
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
