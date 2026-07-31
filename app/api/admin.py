"""Admin API — user registration management and business unit lookups.

All endpoints require the caller to be a registered admin (``is_admin=True``).
The first admin is bootstrapped via the ``ADMIN_UPNS`` env var at application startup.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..email_templates import build_welcome_email
from ..graph import client as graph
from ..models import BusinessUnit, RegisteredUser
from ..schemas import BusinessUnitOut, RegisteredUserOut, RegisterUserIn, UpdateUserIn
from .deps import current_user

settings = get_settings()

router = APIRouter(prefix="/admin", tags=["admin"])


async def _require_admin(upn: str = Depends(current_user), db: AsyncSession = Depends(get_db)) -> str:
    """FastAPI dependency: reject non-admin callers with 403."""
    user = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    if not user or not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return upn


def _user_to_out(u: RegisteredUser) -> RegisteredUserOut:
    """Convert a RegisteredUser ORM row to its API response shape."""
    return RegisteredUserOut(
        upn=u.upn,
        display_name=u.display_name,
        business_unit_id=u.business_unit_id,
        business_unit_name=u.business_unit.name if u.business_unit else None,
        is_admin=u.is_admin,
        is_subscribed=u.is_subscribed,
        subscribed_at=u.subscribed_at.isoformat() if u.subscribed_at else None,
        registered_at=u.registered_at.isoformat(),
    )


@router.get("/business-units", response_model=list[BusinessUnitOut])
async def list_business_units(db: AsyncSession = Depends(get_db),
                               _upn: str = Depends(current_user)):
    """Return all available business units.  Any authenticated domain user can call this."""
    rows = (await db.scalars(select(BusinessUnit).order_by(BusinessUnit.name))).all()
    return [BusinessUnitOut(id=b.id, name=b.name) for b in rows]


@router.get("/users", response_model=list[RegisteredUserOut])
async def list_users(db: AsyncSession = Depends(get_db), _upn: str = Depends(_require_admin)):
    """Return all registered platform users with their business unit assignment."""
    from sqlalchemy.orm import selectinload
    rows = (await db.scalars(
        select(RegisteredUser)
        .options(selectinload(RegisteredUser.business_unit))
        .order_by(RegisteredUser.registered_at)
    )).all()
    return [_user_to_out(u) for u in rows]


@router.post("/users", response_model=RegisteredUserOut, status_code=201)
async def register_user(body: RegisterUserIn, db: AsyncSession = Depends(get_db),
                        _upn: str = Depends(_require_admin)):
    """Register a new @taxconsulting.co.za user and assign them to a business unit."""
    from sqlalchemy.orm import selectinload

    existing = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == body.upn))
    if existing:
        raise HTTPException(409, f"{body.upn} is already registered")

    if body.business_unit_id is not None:
        bu = await db.get(BusinessUnit, body.business_unit_id)
        if not bu:
            raise HTTPException(404, "Business unit not found")

    user = RegisteredUser(
        upn=body.upn,
        display_name=body.display_name,
        business_unit_id=body.business_unit_id,
        is_admin=body.is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # reload with relationship so business_unit_name is available
    user = await db.scalar(
        select(RegisteredUser)
        .where(RegisteredUser.upn == body.upn)
        .options(selectinload(RegisteredUser.business_unit))
    )

    if settings.emails_enabled:
        try:
            bu_name = user.business_unit.name if user.business_unit else None
            subject, html = build_welcome_email(
                upn=user.upn,
                display_name=user.display_name,
                business_unit=bu_name,
                app_url=settings.app_url,
            )
            await graph.send_mail(
                sender=settings.mail_sender_upn or "stanley@taxconsulting.co.za",
                to_upns=[user.upn],
                subject=subject,
                html_body=html,
            )
        except Exception:
            pass  # never let a failed welcome email roll back the registration

    return _user_to_out(user)


@router.patch("/users/{upn}", response_model=RegisteredUserOut)
async def update_user(upn: str, body: UpdateUserIn, db: AsyncSession = Depends(get_db),
                      _admin_upn: str = Depends(_require_admin)):
    """Update an existing registered user's display name, business unit, or admin flag."""
    from sqlalchemy.orm import selectinload

    user = await db.scalar(
        select(RegisteredUser)
        .where(RegisteredUser.upn == upn)
        .options(selectinload(RegisteredUser.business_unit))
    )
    if not user:
        raise HTTPException(404, f"{upn} is not registered")

    if body.business_unit_id is not None:
        bu = await db.get(BusinessUnit, body.business_unit_id)
        if not bu:
            raise HTTPException(404, "Business unit not found")

    if body.display_name is not None:
        user.display_name = body.display_name
    if body.business_unit_id is not None:
        user.business_unit_id = body.business_unit_id
    if body.is_admin is not None:
        user.is_admin = body.is_admin

    await db.commit()
    user = await db.scalar(
        select(RegisteredUser)
        .where(RegisteredUser.upn == upn)
        .options(selectinload(RegisteredUser.business_unit))
    )
    return _user_to_out(user)


@router.delete("/users/{upn}", status_code=204)
async def remove_user(upn: str, db: AsyncSession = Depends(get_db),
                      admin_upn: str = Depends(_require_admin)):
    """Remove a user from the platform.  An admin cannot remove themselves."""
    if upn == admin_upn:
        raise HTTPException(400, "Cannot remove your own admin account")

    user = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    if not user:
        raise HTTPException(404, f"{upn} is not registered")

    await db.delete(user)
    await db.commit()
