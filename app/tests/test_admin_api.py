"""Tests for app/api/admin.py and app/api/users.py — registration management."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app():
    """Build a minimal FastAPI app with admin + users routers for isolation."""
    from app.api.admin import router as admin_router
    from app.api.users import router as users_router
    from app.db import get_db
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(users_router)
    return app, get_db


def _admin_user(upn="admin@taxconsulting.co.za"):
    u = MagicMock()
    u.upn = upn
    u.display_name = "Admin User"
    u.business_unit_id = 1
    u.is_admin = True
    u.registered_at = MagicMock()
    u.registered_at.isoformat.return_value = "2026-06-01T10:00:00"
    u.business_unit = MagicMock()
    u.business_unit.name = "IT and Devs"
    return u


def _member_user(upn="member@taxconsulting.co.za"):
    u = MagicMock()
    u.upn = upn
    u.display_name = "Member User"
    u.business_unit_id = 2
    u.is_admin = False
    u.registered_at = MagicMock()
    u.registered_at.isoformat.return_value = "2026-06-02T08:00:00"
    u.business_unit = MagicMock()
    u.business_unit.name = "Tax Technical"
    return u


class TestListBusinessUnits:
    def test_returns_business_units(self):
        from app.models import BusinessUnit as BU

        app, get_db = _make_app()

        bu1 = MagicMock(spec=BU)
        bu1.id = 1
        bu1.name = "Tax Technical"
        bu2 = MagicMock(spec=BU)
        bu2.id = 2
        bu2.name = "IT and Devs"

        async def override_db():
            mock_db = AsyncMock()
            mock_db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[bu1, bu2])))
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        resp = client.get("/admin/business-units", headers={"x-user-upn": "user@taxconsulting.co.za"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "Tax Technical"

    def test_rejects_outside_domain(self):
        app, get_db = _make_app()

        async def override_db():
            yield AsyncMock()

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/admin/business-units", headers={"x-user-upn": "user@otherdomain.com"})
        assert resp.status_code == 403


class TestListUsers:
    def test_admin_can_list_users(self):
        app, get_db = _make_app()
        admin = _admin_user()

        async def override_db():
            mock_db = AsyncMock()
            # First scalar call: admin lookup for _require_admin
            # Second scalars call: list all users
            mock_db.scalar = AsyncMock(return_value=admin)
            scalars_result = MagicMock()
            scalars_result.all.return_value = [admin]
            mock_db.scalars = AsyncMock(return_value=scalars_result)
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        resp = client.get("/admin/users", headers={"x-user-upn": "admin@taxconsulting.co.za"})
        assert resp.status_code == 200
        users = resp.json()
        assert len(users) == 1
        assert users[0]["upn"] == "admin@taxconsulting.co.za"
        assert users[0]["is_admin"] is True

    def test_non_admin_gets_403(self):
        app, get_db = _make_app()
        member = _member_user()

        async def override_db():
            mock_db = AsyncMock()
            mock_db.scalar = AsyncMock(return_value=member)
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/admin/users", headers={"x-user-upn": "member@taxconsulting.co.za"})
        assert resp.status_code == 403

    def test_unregistered_user_gets_403(self):
        app, get_db = _make_app()

        async def override_db():
            mock_db = AsyncMock()
            mock_db.scalar = AsyncMock(return_value=None)  # not registered
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/admin/users", headers={"x-user-upn": "ghost@taxconsulting.co.za"})
        assert resp.status_code == 403


class TestRegisterUser:
    def test_rejects_non_taxconsulting_upn(self):
        from pydantic import ValidationError
        from app.schemas import RegisterUserIn
        with pytest.raises(ValidationError):
            RegisterUserIn(upn="user@gmail.com")

    def test_accepts_taxconsulting_upn(self):
        from app.schemas import RegisterUserIn
        r = RegisterUserIn(upn="Alice@TaxConsulting.co.za")
        assert r.upn == "alice@taxconsulting.co.za"  # normalised to lowercase

    def test_duplicate_registration_returns_409(self):
        app, get_db = _make_app()
        admin = _admin_user()
        existing_member = _member_user()

        async def override_db():
            mock_db = AsyncMock()
            # _require_admin lookup → admin; duplicate check → existing_member
            call_count = 0

            async def mock_scalar(stmt):
                nonlocal call_count
                call_count += 1
                return admin if call_count == 1 else existing_member

            mock_db.scalar = mock_scalar
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/admin/users",
            json={"upn": "member@taxconsulting.co.za", "business_unit_id": 1},
            headers={"x-user-upn": "admin@taxconsulting.co.za"},
        )
        assert resp.status_code == 409


class TestRemoveUser:
    def test_admin_cannot_remove_self(self):
        app, get_db = _make_app()
        admin = _admin_user()

        async def override_db():
            mock_db = AsyncMock()
            mock_db.scalar = AsyncMock(return_value=admin)
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(
            "/admin/users/admin%40taxconsulting.co.za",
            headers={"x-user-upn": "admin@taxconsulting.co.za"},
        )
        assert resp.status_code == 400

    def test_removing_nonexistent_user_returns_404(self):
        app, get_db = _make_app()
        admin = _admin_user()

        async def override_db():
            mock_db = AsyncMock()
            call_count = 0

            async def mock_scalar(stmt):
                nonlocal call_count
                call_count += 1
                return admin if call_count == 1 else None  # admin found, target not found

            mock_db.scalar = mock_scalar
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(
            "/admin/users/ghost%40taxconsulting.co.za",
            headers={"x-user-upn": "admin@taxconsulting.co.za"},
        )
        assert resp.status_code == 404


class TestGetMe:
    def test_registered_user_returns_200(self):
        app, get_db = _make_app()
        user = _member_user()

        async def override_db():
            mock_db = AsyncMock()
            mock_db.scalar = AsyncMock(return_value=user)
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        resp = client.get("/users/me", headers={"x-user-upn": "member@taxconsulting.co.za"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["upn"] == "member@taxconsulting.co.za"
        assert data["is_admin"] is False

    def test_unregistered_user_returns_404(self):
        app, get_db = _make_app()

        async def override_db():
            mock_db = AsyncMock()
            mock_db.scalar = AsyncMock(return_value=None)
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/users/me", headers={"x-user-upn": "unknown@taxconsulting.co.za"})
        assert resp.status_code == 404

    def test_admin_flag_reflected(self):
        app, get_db = _make_app()
        admin = _admin_user()

        async def override_db():
            mock_db = AsyncMock()
            mock_db.scalar = AsyncMock(return_value=admin)
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        resp = client.get("/users/me", headers={"x-user-upn": "admin@taxconsulting.co.za"})
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is True


class TestShareMeetingSchema:
    def test_rejects_non_taxconsulting_recipient(self):
        from pydantic import ValidationError
        from app.schemas import ShareMeetingIn
        with pytest.raises(ValidationError):
            ShareMeetingIn(recipient_upn="someone@gmail.com")

    def test_accepts_taxconsulting_recipient(self):
        from app.schemas import ShareMeetingIn
        s = ShareMeetingIn(recipient_upn="Alice@TaxConsulting.co.za")
        assert s.recipient_upn == "alice@taxconsulting.co.za"
