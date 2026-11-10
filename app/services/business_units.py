"""Business Unit catalog and assignment history."""
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text

from ..models import AuditEvent, BusinessUnit, RegisteredUser


async def record_assignment(db, user, actor, unit_id):
    if user.business_unit_id == unit_id:
        return
    actor_id = user.id if actor == user.upn else await db.scalar(
        select(RegisteredUser.id).where(RegisteredUser.upn == actor)
    )
    event_id = uuid4()
    db.add(AuditEvent(
        id=event_id, event_type="business_unit.assigned", outcome="succeeded",
        actor_type="user", actor_id=str(actor_id) if actor_id else "configured-admin", actor_upn=actor,
        resource_type="registered_user", resource_id=user.id,
        correlation_id=event_id, event_key=str(event_id),
        event_metadata={"previous_unit_id": user.business_unit_id, "unit_id": unit_id},
    ))
    user.business_unit_id = unit_id
    user.business_unit_version += 1


def selectable_units():
    return select(BusinessUnit).where(BusinessUnit.is_selectable.is_(True))


async def require_selectable_unit(db, unit_id):
    if await db.scalar(selectable_units().where(BusinessUnit.id == unit_id)) is None:
        raise HTTPException(404, "Selectable Business Unit not found.")


def require_assignment_version(user, version):
    if version != user.business_unit_version:
        raise HTTPException(409, "Business Unit assignment changed. Refresh and try again.")


async def create_unit(db, raw_name):
    name = " ".join(raw_name.split())
    if not name or len(name) > 100:
        raise HTTPException(422, "Enter a Business Unit name of 1 to 100 characters.")
    # Serialize normalized-name checks, including names on historical rows.
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("LOCK TABLE business_units IN SHARE ROW EXCLUSIVE MODE"))
    else:
        await db.execute(text("BEGIN IMMEDIATE"))
    names = await db.scalars(select(BusinessUnit.name))
    if any(" ".join(existing.split()).casefold() == name.casefold() for existing in names):
        raise HTTPException(409, "This Business Unit already exists.")
    unit = BusinessUnit(name=name, is_selectable=True)
    db.add(unit)
    await db.flush()
    return unit
