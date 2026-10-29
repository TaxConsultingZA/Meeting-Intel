"""No real PostgreSQL or HTTP calls; exercise shared admission failure boundaries."""
from unittest.mock import AsyncMock, MagicMock
import ssl

import pytest
from pydantic import SecretStr

from app.ai import businessai_test_permit as permits
from app.ai.businessai import BusinessAIConfig, BusinessAIProvider
from app.ai.contracts import ProcessingRequest, Segment
from app.ai.providers import ProviderFailure
from app.ai.runtime_bridge import get_local_provider, FoundationExtractionError
from uuid import uuid4


@pytest.mark.parametrize("admitted", [permits.PERMIT_ID, None])
async def test_shared_unique_insert_is_committed_and_never_refunded(monkeypatch, admitted):
    connection = MagicMock()
    connection.fetchval = AsyncMock(side_effect=[True, admitted])
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(permits.asyncpg, "connect", connect)
    if admitted:
        await permits.consume_test_permit(SecretStr("postgresql://offline.invalid/test"))
    else:
        with pytest.raises(ProviderFailure):
            await permits.consume_test_permit(SecretStr("postgresql://offline.invalid/test"))
    sql, identifier = connection.fetchval.call_args.args
    assert "ON CONFLICT (permit_id) DO NOTHING" in sql
    assert identifier == permits.PERMIT_ID
    assert "DELETE" not in sql and "UPDATE" not in sql
    tls = connect.call_args.kwargs['ssl']
    assert tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED
    connection.terminate.assert_called_once()


@pytest.mark.parametrize('acceptable', [False, None, 'true'])
async def test_unsafe_or_missing_store_denies_without_consuming(monkeypatch, acceptable):
    connection = MagicMock()
    connection.fetchval = AsyncMock(return_value=acceptable)
    monkeypatch.setattr(permits.asyncpg, 'connect', AsyncMock(return_value=connection))
    with pytest.raises(ProviderFailure):
        await permits.consume_test_permit(SecretStr('postgresql://offline.invalid/test'))
    assert connection.fetchval.await_count == 1
    assert connection.fetchval.call_args.args == (permits.STORE_CHECK,)
    connection.terminate.assert_called_once()


@pytest.mark.parametrize("dsn", ["", "sqlite:///local", "postgresql://offline.invalid/test"])
async def test_missing_or_failed_shared_database_denies(monkeypatch, dsn):
    monkeypatch.setattr(permits.asyncpg, "connect", AsyncMock(side_effect=RuntimeError("private")))
    with pytest.raises(ProviderFailure) as error:
        await permits.consume_test_permit(SecretStr(dsn))
    assert str(error.value) == "configuration"


def test_meeting_runtime_never_selects_businessai_even_when_enabled(monkeypatch):
    monkeypatch.setenv("BUSINESSAI_ENABLED", "true")
    with pytest.raises(FoundationExtractionError):
        get_local_provider("businessai")


async def test_non_synthetic_transcript_is_rejected_before_any_admission(tmp_path, monkeypatch):
    from app.ai import businessai
    permit = AsyncMock(side_effect=AssertionError("admission attempted"))
    client = MagicMock(side_effect=AssertionError("HTTP attempted"))
    monkeypatch.setattr(businessai, "consume_test_permit", permit)
    monkeypatch.setattr(businessai.httpx, "AsyncClient", client)
    config = BusinessAIConfig(enabled=True, synthetic_test_enabled=True,
        chat_url="https://api.businessai.co.za/v1/chat/completions", model_id="test-model",
        api_key=SecretStr("fake-key"), ledger_path=str(tmp_path / "usage.sqlite"))
    request = ProcessingRequest(meeting_id=uuid4(), segments=(
        Segment(id="s1", speaker="Speaker A", text="Other input"),))
    with pytest.raises(ProviderFailure):
        await BusinessAIProvider(config).process(request)
    permit.assert_not_awaited()
    client.assert_not_called()


def test_synthetic_gate_defaults_closed_and_secrets_are_excluded(tmp_path):
    config = BusinessAIConfig(enabled=True, api_key=SecretStr("fake-key"),
        permit_database_url=SecretStr("postgresql://private.invalid/test"))
    assert "fake-key" not in config.model_dump_json()
    assert "private.invalid" not in config.model_dump_json()
    with pytest.raises(ProviderFailure):
        BusinessAIProvider(config)
