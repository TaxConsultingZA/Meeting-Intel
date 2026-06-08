"""User self-service API — lets the frontend check the caller's registration status."""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..email_templates import build_welcome_email
from ..graph import client as graph
from ..models import RegisteredUser
from ..schemas import RegisteredUserOut
from .deps import current_user

log = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=RegisteredUserOut)
async def get_me(db: AsyncSession = Depends(get_db), upn: str = Depends(current_user)):
    """Return the registration record for the caller, auto-registering them on first login.

    Any user whose UPN ends in the allowed domain is registered automatically the
    first time they call this endpoint.  A welcome email is sent if emails are enabled.
    """
    user = await db.scalar(
        select(RegisteredUser)
        .where(RegisteredUser.upn == upn)
        .options(selectinload(RegisteredUser.business_unit))
    )

    if not user:
        # Auto-register any @taxconsulting.co.za user on first login
        user = RegisteredUser(upn=upn, is_admin=False)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        log.info("Auto-registered user on first login: %s", upn)

        if settings.emails_enabled:
            try:
                subject, html = build_welcome_email(
                    upn=upn,
                    display_name=None,
                    business_unit=None,
                    app_url=settings.app_url,
                )
                await graph.send_mail(
                    sender=settings.mail_sender_upn or "stanley@taxconsulting.co.za",
                    recipients=[upn],
                    subject=subject,
                    body=html,
                )
            except Exception:
                pass  # never let a failed welcome email block login

        user = await db.scalar(
            select(RegisteredUser)
            .where(RegisteredUser.upn == upn)
            .options(selectinload(RegisteredUser.business_unit))
        )

    return RegisteredUserOut(
        upn=user.upn,
        display_name=user.display_name,
        business_unit_id=user.business_unit_id,
        business_unit_name=user.business_unit.name if user.business_unit else None,
        is_admin=user.is_admin,
        registered_at=user.registered_at.isoformat(),
    )
