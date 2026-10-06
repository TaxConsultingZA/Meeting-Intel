"""Request-local status timing without response, SQL, or identity disclosure."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, literal, select
from sqlalchemy.orm import Session

from app.api import deps, recording_jobs
from app.db import get_db
from app.services import status_diagnostics as diagnostics


def metrics(caplog):
    return [json.loads(record.getMessage().split(" ", 1)[1])
            for record in caplog.records if record.getMessage().startswith("recording_status_performance ")]


def timing():
    return {"authentication_ms": 0.0, "db_session_ms": 0.0,
            "db_connection_ms": 0.0, "db_query_ms": 0.0,
            "serialization_started": None, "depth": {}}


def app_with_status():
    app = FastAPI()
    app.include_router(recording_jobs.router)
    return app


def test_status_response_unchanged_and_logs_safe_fields(caplog):
    caplog.set_level("INFO", logger="uvicorn.error")
    app = app_with_status()
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[deps.registered_user] = lambda: SimpleNamespace(upn="SECRET@example.test", is_admin=True)
    response = TestClient(app).get("/recordings/jobs?limit=12", headers={"Authorization": "Bearer SECRET"})
    assert response.status_code == 200 and response.json() == []
    assert "diagnostic_id" not in response.headers
    record, = metrics(caplog)
    assert record["status_code"] == 200
    for field in ("authentication_ms", "db_session_ms", "db_connection_ms", "db_query_ms", "serialization_ms", "total_endpoint_ms"):
        assert record[field] >= 0
    assert record["total_endpoint_ms"] >= record["serialization_ms"]
    assert "SECRET" not in json.dumps(record)
    assert "limit" not in record and "query" not in record
    assert diagnostics._current.get() is None


def test_auth_failure_is_logged_without_identity_or_exception(caplog):
    caplog.set_level("INFO", logger="uvicorn.error")
    app = app_with_status()
    app.dependency_overrides[get_db] = lambda: MagicMock()

    async def denied():
        with diagnostics.measure("authentication_ms"):
            raise HTTPException(403, "SECRET")

    app.dependency_overrides[deps.registered_user] = denied
    response = TestClient(app).get("/recordings/jobs")
    assert response.status_code == 403
    record, = metrics(caplog)
    assert record["status_code"] == 403
    assert record["serialization_ms"] is None
    assert "SECRET" not in json.dumps(record)


def test_query_failure_is_logged_and_context_reset(caplog):
    caplog.set_level("INFO", logger="uvicorn.error")
    app = app_with_status()
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("SECRET DB URL"))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[deps.registered_user] = lambda: SimpleNamespace(upn="SECRET", is_admin=True)
    response = TestClient(app, raise_server_exceptions=False).get("/recordings/jobs")
    assert response.status_code == 500
    record, = metrics(caplog)
    assert record["status_code"] == 500
    assert "SECRET" not in json.dumps(record)
    assert diagnostics._current.get() is None


def test_invalid_filter_logs_actual_validation_status(caplog):
    caplog.set_level("INFO", logger="uvicorn.error")
    app = app_with_status()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[deps.registered_user] = lambda: SimpleNamespace(upn="SECRET", is_admin=True)
    response = TestClient(app).get("/recordings/jobs?meeting_id=PRIVATE-invalid-value")
    assert response.status_code == 422
    record, = metrics(caplog)
    assert record["status_code"] == 422
    assert "PRIVATE" not in json.dumps(record)


def test_other_routes_emit_no_diagnostic(caplog):
    caplog.set_level("INFO", logger="uvicorn.error")
    app = FastAPI()
    router = diagnostics.RecordingStatusRoute
    app.router.route_class = router

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    assert TestClient(app).get("/health").json() == {"status": "ok"}
    assert not metrics(caplog)


def test_database_timings_use_real_public_connection_resolution_without_extra_sql():
    engine = create_engine("sqlite://")
    from sqlalchemy import event
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, params, context, many: statements.append(statement))
    record = timing()
    token = diagnostics._current.set(record)
    try:
        with Session(engine) as session:
            assert session.scalar(select(literal("SECRET"))) == "SECRET"
            assert session.scalar(select(literal(2))) == 2
            assert session.in_transaction()
        assert len(statements) == 2
        assert record["db_connection_ms"] > 0
        assert record["db_query_ms"] > 0
        assert "SECRET" not in json.dumps(record)
    finally:
        diagnostics._current.reset(token)
        engine.dispose()


async def test_authentication_decorator_preserves_return_and_exception():
    @diagnostics.authentication_timing
    async def authenticate(deny=False):
        if deny:
            raise HTTPException(401)
        return "unchanged"

    record = timing()
    token = diagnostics._current.set(record)
    try:
        assert await authenticate() == "unchanged"
        with pytest.raises(HTTPException):
            await authenticate(True)
        assert record["authentication_ms"] > 0
    finally:
        diagnostics._current.reset(token)


async def test_concurrent_requests_have_independent_timings(caplog):
    caplog.set_level("INFO", logger="uvicorn.error")
    app = app_with_status()
    app.dependency_overrides[get_db] = lambda: MagicMock(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))

    async def user():
        with diagnostics.measure("authentication_ms"):
            await asyncio.sleep(0)
            return SimpleNamespace(upn="SECRET", is_admin=True)

    app.dependency_overrides[deps.registered_user] = user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(client.get("/recordings/jobs"), client.get("/recordings/jobs"))
    assert all(response.json() == [] for response in responses)
    records = metrics(caplog)
    assert len(records) == 2
    assert records[0]["diagnostic_id"] != records[1]["diagnostic_id"]
    assert all(record["authentication_ms"] > 0 for record in records)
    assert diagnostics._current.get() is None


def test_logging_failure_cannot_change_response(monkeypatch):
    app = app_with_status()
    app.dependency_overrides[get_db] = lambda: MagicMock(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    app.dependency_overrides[deps.registered_user] = lambda: SimpleNamespace(upn="SECRET", is_admin=True)
    monkeypatch.setattr(diagnostics.log, "info", MagicMock(side_effect=RuntimeError("log unavailable")))
    response = TestClient(app).get("/recordings/jobs")
    assert response.status_code == 200 and response.json() == []
