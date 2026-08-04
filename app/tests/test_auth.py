"""Security boundary tests for bearer-token authentication."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


def _claims(**overrides):
    claims = {
        "sub": "subject",
        "oid": "immutable-object-id",
        "tid": "tenant-id",
        "preferred_username": "alice@taxconsulting.co.za",
        "scp": "access_as_user",
    }
    claims.update(overrides)
    return claims


def test_entra_validator_checks_signature_audience_issuer_and_required_claims(monkeypatch):
    from app.auth import entra

    jwks = MagicMock()
    jwks.get_signing_key_from_jwt.return_value = SimpleNamespace(key="public-key")
    monkeypatch.setattr(entra, "_jwks_client", lambda: jwks)
    monkeypatch.setattr(entra.settings if hasattr(entra, "settings") else entra.get_settings(), "tenant_id", "tenant-id")
    settings = entra.get_settings()
    monkeypatch.setattr(settings, "entra_api_audience", "api-client-id")
    monkeypatch.setattr(settings, "entra_required_scope", "access_as_user")
    decode = MagicMock(return_value=_claims())
    monkeypatch.setattr(entra.jwt, "decode", decode)

    assert entra.validate_access_token("signed.jwt")["tid"] == "tenant-id"
    _, kwargs = decode.call_args
    assert kwargs["audience"] == "api-client-id"
    assert kwargs["issuer"] == "https://login.microsoftonline.com/tenant-id/v2.0"
    assert kwargs["algorithms"] == ["RS256"]


def test_entra_validator_rejects_missing_api_scope(monkeypatch):
    from app.auth import entra

    jwks = MagicMock()
    jwks.get_signing_key_from_jwt.return_value = SimpleNamespace(key="public-key")
    monkeypatch.setattr(entra, "_jwks_client", lambda: jwks)
    settings = entra.get_settings()
    monkeypatch.setattr(settings, "tenant_id", "tenant-id")
    monkeypatch.setattr(settings, "entra_api_audience", "api-client-id")
    monkeypatch.setattr(settings, "entra_required_scope", "access_as_user")
    monkeypatch.setattr(entra.jwt, "decode", lambda *args, **kwargs: _claims(scp="other"))

    with pytest.raises(HTTPException) as exc:
        entra.validate_access_token("signed.jwt")
    assert exc.value.status_code == 403


async def test_current_user_resolves_renamed_upn_by_immutable_oid(monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps.settings, "auth_mode", "entra")
    monkeypatch.setattr(deps, "validate_access_token", lambda token: _claims(
        preferred_username="new.name@taxconsulting.co.za"
    ))
    existing = MagicMock(upn="old.name@taxconsulting.co.za")
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=existing)

    result = await deps.current_user(
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed.jwt"),
        db=db,
    )
    assert result == "old.name@taxconsulting.co.za"


async def test_current_user_rejects_upn_bound_to_different_oid(monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps.settings, "auth_mode", "entra")
    monkeypatch.setattr(deps, "validate_access_token", lambda token: _claims())
    conflicting = MagicMock(upn="alice@taxconsulting.co.za", entra_oid="different-oid")
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[None, conflicting])

    with pytest.raises(HTTPException) as exc:
        await deps.current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed.jwt"),
            db=db,
        )
    assert exc.value.status_code == 403


async def test_hybrid_mode_accepts_only_whitelisted_mock_accounts(monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps.settings, "auth_mode", "hybrid")
    monkeypatch.setattr(deps.settings, "graph_impl", "mock")
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock(upn="demo@taxconsulting.co.za"))

    result = await deps.current_user(
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="mock:demo@taxconsulting.co.za"
        ),
        db=db,
    )
    assert result == "demo@taxconsulting.co.za"


async def test_hybrid_mode_rejects_unregistered_mock_account(monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps.settings, "auth_mode", "hybrid")
    monkeypatch.setattr(deps.settings, "graph_impl", "mock")
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await deps.current_user(
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="mock:not-listed@taxconsulting.co.za"
            ),
            db=db,
        )
    assert exc.value.status_code == 403


async def test_hybrid_mode_still_validates_real_entra_tokens(monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps.settings, "auth_mode", "hybrid")
    monkeypatch.setattr(deps, "validate_access_token", lambda token: _claims())
    existing = MagicMock(upn="alice@taxconsulting.co.za")
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=existing)

    result = await deps.current_user(
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed.jwt"),
        db=db,
    )
    assert result == "alice@taxconsulting.co.za"
