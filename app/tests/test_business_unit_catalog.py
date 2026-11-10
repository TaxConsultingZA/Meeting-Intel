"""Exercise BU provisioning and selection with synthetic users and no API lifespan."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import admin, users
from app.api.deps import current_user
from app.db import get_db
from app.models import AuditEvent, BusinessUnit, RegisteredUser


EXPECTED_NAMES = {
    "Africorp", "AI Department", "BAM", "CPD Consortium", "Crypto Tax consulting",
    "DEV", "FBPS", "FE", "IT", "Marketing", "MySarsAssistant", "Rem",
    "SubmitMyVisa", "TRS", "Xpatweb",
}
EXTRA_NAMES = {
    "Tax Technical", "xpatweb", "Financial Emigration", "IT and Devs",
    "Synthetic Operations", "ABSA Trust Portal", "Accounting Team",
}


@pytest.fixture
async def catalog_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            for model in (BusinessUnit, RegisteredUser, AuditEvent):
                await connection.run_sync(model.__table__.create)
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def initialize(engine):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / (
        "68c4a7fe210d_seed_initial_business_units.py"
    )
    spec = spec_from_file_location("seed_initial_business_units", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    async with engine.begin() as connection:
        await connection.run_sync(upgrade)


async def test_fresh_catalog_exactly_matches_screenshot(catalog_db):
    engine, sessions = catalog_db
    await initialize(engine)
    async with sessions() as db:
        names = (await db.scalars(select(BusinessUnit.name))).all()
    assert sorted(names) == sorted(EXPECTED_NAMES)


async def test_seed_retry_preserves_assignments_and_limits_new_choices(catalog_db):
    engine, sessions = catalog_db
    admin_upn = "admin@example.test"
    legacy_upn = "legacy@example.test"
    member_upn = "member@example.test"
    async with sessions.begin() as db:
        db.add_all(BusinessUnit(name=name) for name in sorted(EXTRA_NAMES | {"IT"}))
        await db.flush()
        it = await db.scalar(select(BusinessUnit).where(BusinessUnit.name == "IT"))
        legacy = await db.scalar(select(BusinessUnit).where(BusinessUnit.name == "xpatweb"))
        it_id, legacy_id = it.id, legacy.id
        db.add_all([
            RegisteredUser(upn=admin_upn, is_admin=True, business_unit_id=it_id),
            RegisteredUser(upn=legacy_upn, business_unit_id=legacy_id),
            RegisteredUser(upn=member_upn),
        ])

    async def snapshot():
        async with sessions() as db:
            units = dict((await db.execute(select(BusinessUnit.name, BusinessUnit.id))).all())
            assignments = dict((await db.execute(
                select(RegisteredUser.upn, RegisteredUser.business_unit_id)
            )).all())
            return units, assignments

    before_units, before_assignments = await snapshot()
    await initialize(engine)
    first_units, first_assignments = await snapshot()
    await initialize(engine)
    assert await snapshot() == (first_units, first_assignments)
    assert first_assignments == before_assignments
    assert {name: first_units[name] for name in before_units} == before_units
    assert first_units.keys() == EXPECTED_NAMES | EXTRA_NAMES

    # SQLite exercises the API against the phase-two schema. Alembic upgrade is
    # verified separately against the isolated PostgreSQL acceptance database.
    async with sessions.begin() as db:
        await db.execute(update(BusinessUnit).where(
            BusinessUnit.name.in_(EXPECTED_NAMES)
        ).values(is_selectable=True))

    async def database():
        async with sessions() as db:
            yield db

    def identity(request: Request):
        return request.headers.get("x-test-upn", member_upn)

    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(users.router)
    app.dependency_overrides.update({get_db: database, current_user: identity})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/business-units")
        assert response.status_code == 200
        assert sorted(unit["name"] for unit in response.json()) == sorted(EXPECTED_NAMES)
        historical_url = "/admin/business-units?include_historical=true"
        assert (await client.get(historical_url)).status_code == 403
        response = await client.get(historical_url, headers={"x-test-upn": admin_upn})
        assert response.status_code == 200
        assert {unit["name"] for unit in response.json() if not unit["is_selectable"]} == EXTRA_NAMES

        choice_url = "/users/me/business-unit"
        assert (await client.put(choice_url, json={"name": "Accounting Team"})).status_code == 422
        assert (await client.put(choice_url, json={"business_unit_id": legacy_id, "business_unit_version": 0})).status_code == 404
        response = await client.put(choice_url, json={"business_unit_id": first_units["Xpatweb"], "business_unit_version": 0})
        assert response.status_code == 200
        assert response.json()["business_unit_name"] == "Xpatweb"
        assert (await client.put(choice_url, json={"business_unit_id": it_id, "business_unit_version": 1})).status_code == 409

        headers = {"x-test-upn": admin_upn}
        response = await client.patch(f"/admin/users/{legacy_upn}", headers=headers, json={
            "display_name": "Synthetic legacy member",
        })
        assert response.status_code == 200
        assert response.json()["business_unit_name"] == "xpatweb"
        target_url = f"/admin/users/{member_upn}"
        assert (await client.patch(target_url, headers=headers, json={
            "business_unit_id": legacy_id, "business_unit_version": 1,
        })).status_code == 404
        response = await client.patch(target_url, headers=headers, json={"business_unit_id": it_id, "business_unit_version": 1})
        assert response.status_code == 200
        assert response.json()["business_unit_name"] == "IT"

        create_url = "/admin/business-units"
        assert (await client.post(create_url, json={"name": "Future Team"})).status_code == 403
        assert (await client.post(create_url, headers=headers, json={"name": "  "})).status_code == 422
        assert (await client.post(create_url, headers=headers, json={"name": " XPATWEB "})).status_code == 409
        response = await client.post(create_url, headers=headers, json={"name": "  Future   Team  "})
        assert response.status_code == 201
        new_unit = response.json()
        assert new_unit["name"] == "Future Team"
        assert (await client.post(create_url, headers=headers, json={"name": "future team"})).status_code == 409
        assert new_unit in (await client.get(create_url)).json()

        # A previously opened page must not overwrite an intervening correction,
        # even if a later admin clears the assignment back to Unassigned.
        cleared = await client.patch(target_url, headers=headers, json={
            "business_unit_id": None, "business_unit_version": 2,
        })
        assert cleared.status_code == 200
        assert cleared.json()["business_unit_version"] == 3
        stale = {"business_unit_id": new_unit["id"], "business_unit_version": 2}
        assert (await client.put(choice_url, json=stale)).status_code == 409
        assert (await client.patch(target_url, headers=headers, json=stale)).status_code == 409
        assert (await client.patch(target_url, json={**stale, "business_unit_version": 3})).status_code == 403
        assert (await client.put(choice_url, json={**stale, "business_unit_version": 3, "upn": legacy_upn})).status_code == 422
        chosen = await client.put(choice_url, json={**stale, "business_unit_version": 3})
        assert chosen.status_code == 200
        assert chosen.json()["business_unit_name"] == "Future Team"
        assert (await client.get("/users/me")).json()["business_unit_name"] == "Future Team"
