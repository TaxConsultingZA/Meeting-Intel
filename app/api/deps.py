"""Shared FastAPI dependencies used across multiple routers."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..auth.entra import validate_access_token
from ..db import get_db
from ..models import RegisteredUser

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


def _domain_user(upn: str) -> str:
    normalized = upn.strip().lower()
    if not normalized.endswith("@" + settings.allowed_domain.lower()):
        raise HTTPException(403, "Outside allowed domain")
    return normalized


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Authenticate the caller using a bearer token.

    Production validates a Microsoft Entra access token for this API. Local
    Mock mode accepts only the explicit ``Bearer mock:<company-upn>`` format.
    Hybrid mode additionally requires that Mock identity to already exist in
    the registered-user whitelist. The old spoofable ``x-user-upn`` header is
    intentionally unsupported.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Bearer token required")

    token = credentials.credentials
    if settings.auth_mode in {"mock", "hybrid"} and token.startswith("mock:"):
        if settings.graph_impl != "mock":
            raise HTTPException(500, "Mock and Hybrid demo authentication require GRAPH_IMPL=mock")
        upn = _domain_user(token.removeprefix("mock:"))
        if settings.auth_mode == "hybrid":
            registered = await db.scalar(
                select(RegisteredUser).where(RegisteredUser.upn == upn)
            )
            if not registered:
                raise HTTPException(403, "Demo account is not on the registered-user whitelist")
        return upn

    if settings.auth_mode == "mock":
        raise HTTPException(401, "Invalid local Mock token")

    if settings.auth_mode not in {"entra", "hybrid"}:
        raise HTTPException(500, "Unsupported AUTH_MODE")

    claims = validate_access_token(token)
    # ``preferred_username`` is mutable, so it is used only as an addressable
    # company UPN. Authorization is anchored to Entra's immutable object ID.
    upn = claims.get("preferred_username") or claims.get("upn") or claims.get("email")
    if not isinstance(upn, str):
        raise HTTPException(403, "Microsoft token has no addressable company username")
    upn = _domain_user(upn)
    oid = claims.get("oid")
    if not isinstance(oid, str) or not oid:
        raise HTTPException(403, "Microsoft token has no immutable user object ID")

    by_oid = await db.scalar(select(RegisteredUser).where(RegisteredUser.entra_oid == oid))
    if by_oid:
        return by_oid.upn

    by_upn = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    if by_upn:
        if by_upn.entra_oid and by_upn.entra_oid != oid:
            raise HTTPException(403, "Microsoft identity does not match this user record")
        by_upn.entra_oid = oid
        await db.commit()
    return upn


async def require_registered(
    upn: str = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    """FastAPI dependency: verify the caller is a registered platform user.

    Raises 403 for outside-domain UPNs and for domain users not yet registered.
    Use this instead of ``current_user`` on endpoints that should be invisible
    to unregistered domain members.
    """
    user = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    if not user:
        raise HTTPException(403, "Not registered on the platform")
    return upn


async def require_subscribed(
    upn: str = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Allow Microsoft data access only after the user explicitly opts in."""
    user = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    if not user or not user.is_subscribed:
        raise HTTPException(403, "Subscribe before accessing Calendar or OneDrive")
    return upn


async def require_admin(upn: str = ..., db: AsyncSession = ...) -> str:
    """FastAPI dependency: verify the caller is a registered admin.

    Raises 403 if the UPN is not found in ``registered_users`` or is not an admin.
    Must be used together with ``current_user`` — callers should declare both deps.
    """
    user = await db.scalar(select(RegisteredUser).where(RegisteredUser.upn == upn))
    if not user or not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return upn
