"""API restarts must not provision schema or bootstrap reference records."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def test_startup_without_database_and_existing_user_request(monkeypatch, caplog):
    from app import db, main
    from app.models import BusinessUnit, RegisteredUser

    monkeypatch.setattr(main.settings, "enable_scheduled_sync", False)
    monkeypatch.setattr(main.settings, "admin_upns", ["bootstrap@taxconsulting.co.za"])
    forbidden = MagicMock(side_effect=AssertionError("Startup touched the database"))
    blocked_engine = SimpleNamespace(begin=forbidden, connect=forbidden)
    monkeypatch.setattr(main, "engine", blocked_engine)
    monkeypatch.setattr(db, "engine", blocked_engine)
    monkeypatch.setattr(main, "SessionLocal", forbidden)
    monkeypatch.setattr(db, "SessionLocal", forbidden)

    # Provision a pre-existing database outside the API lifecycle, as a fixture.
    local_engine = create_engine("sqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    BusinessUnit.__table__.create(local_engine)
    RegisteredUser.__table__.create(local_engine)
    try:
        with Session(local_engine, expire_on_commit=False) as session:
            session.add(RegisteredUser(upn="existing@taxconsulting.co.za", is_admin=True))
            session.commit()
            request_db = MagicMock()
            request_db.scalar = AsyncMock(side_effect=session.scalar)
            request_db.commit = AsyncMock(side_effect=AssertionError("Read wrote data"))
            previous = main.app.dependency_overrides.copy()
            main.app.dependency_overrides[db.get_db] = lambda: request_db
            try:
                with caplog.at_level("INFO", logger="meeting_intel"), TestClient(main.app) as client:
                    assert client.get("/health").json() == {"status": "ok"}
                    response = client.get("/users/me", headers={
                        "Authorization": "Bearer mock:existing@taxconsulting.co.za",
                    })
                    assert response.status_code == 200
                    assert response.json()["is_admin"] is True
                request_db.scalar.assert_awaited_once()
                request_db.commit.assert_not_awaited()
                forbidden.assert_not_called()
                assert "Scheduled Calendar sync and OneDrive reconciliation disabled" in caplog.text
            finally:
                main.app.dependency_overrides.clear()
                main.app.dependency_overrides.update(previous)
    finally:
        local_engine.dispose()
