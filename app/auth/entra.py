"""Validate Microsoft Entra access tokens presented to the FastAPI backend."""
from functools import lru_cache
import logging

import jwt
from fastapi import HTTPException

from ..config import get_settings


log = logging.getLogger(__name__)


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    settings = get_settings()
    uri = (
        f"https://login.microsoftonline.com/{settings.tenant_id}"
        "/discovery/v2.0/keys"
    )
    # Entra signing keys rotate. PyJWKClient refreshes on an unknown ``kid`` and
    # caches the key set so ordinary requests do not make a network call.
    return jwt.PyJWKClient(uri, cache_keys=True, lifespan=24 * 60 * 60)


def validate_access_token(token: str) -> dict:
    """Return verified claims or raise an API-safe 401/403 response.

    Signature, expiry, audience, issuer, tenant and delegated API scope are all
    checked. A token intended for Microsoft Graph is rejected because its
    audience is not this API.
    """
    settings = get_settings()
    # Entra can issue either a v2 access token or a v1 access token depending
    # on the app registration's requestedAccessTokenVersion setting. Both are
    # valid for this tenant and are signed by the same tenant key set.
    issuers = [
        f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0",
        f"https://sts.windows.net/{settings.tenant_id}/",
    ]
    # Custom API audiences are emitted as either the raw application/client ID
    # or its Application ID URI. Restrict validation to these exact values.
    audiences = list(
        dict.fromkeys(
            [
                settings.api_audience,
                settings.client_id,
                f"api://{settings.client_id}",
            ]
        )
    )
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audiences,
            issuer=issuers,
            options={
                "require": ["exp", "iat", "iss", "aud", "tid", "sub", "oid"],
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, "Microsoft session expired") from exc
    except jwt.PyJWTError as exc:
        log.warning("Microsoft access token validation failed: %s", exc)
        raise HTTPException(401, "Invalid Microsoft access token") from exc
    except Exception as exc:
        raise HTTPException(503, "Could not verify Microsoft access token") from exc

    if claims.get("tid") != settings.tenant_id:
        raise HTTPException(403, "Token was issued by a different Microsoft tenant")

    scopes = set(str(claims.get("scp", "")).split())
    if settings.entra_required_scope not in scopes:
        raise HTTPException(403, "Token is missing the required API scope")
    return claims
