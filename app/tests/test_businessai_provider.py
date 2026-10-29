"""Synthetic chat fixtures only; the shared socket guard prohibits live traffic."""
import asyncio
import json
import logging
import sqlite3
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.ai import businessai, runtime_bridge as bridge
from app.ai.businessai import BusinessAIConfig, BusinessAIProvider
from app.ai.contracts import FailureCode, ProcessingRequest, Segment
from app.ai.processing import process
from app.ai.providers import ProviderFailure
from app.ai.registry import ProviderRegistryError, businessai_runtime_configuration
from app.config import get_settings
from app.pipeline.transcribe import TranscriptSegment


URL = "https://api.businessai.co.za/v1/chat/completions"  # Mocked; sockets are denied.
TEXT = "Please send the report."
KEY = "fake-offline-key"
RESULT = {"summary": "The report was discussed.", "action_items": [{
    "action": "Send the report", "assigned_to": None, "due_date": None,
    "confidence": "medium", "source_quote": TEXT,
}]}
LEDGER_PATH = ""


@pytest.fixture(autouse=True)
def isolated_budget(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), 'LEDGER_PATH', str(tmp_path / 'usage.sqlite'))


def configured(**changes):
    return BusinessAIConfig(**{
        "enabled": True, "chat_url": URL, "model_id": "businessai-chat",
        "api_key": SecretStr(KEY),
        "ledger_path": LEDGER_PATH, "max_requests": 1, "token_budget": 4096,
        **changes,
    })


def request():
    return ProcessingRequest(meeting_id=uuid4(), segments=(
        Segment(id="s1", speaker="Speaker A", text=TEXT),
    ))


def response(result=RESULT, finish_reason="stop"):
    return {"usage": {"prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120}, "choices": [{"finish_reason": finish_reason,
                         "message": {"role": "assistant", "content": json.dumps(result)}}]}


def runtime_settings(monkeypatch, **changes):
    settings = get_settings()
    values = {"businessai_enabled": True, "businessai_chat_url": URL,
              "businessai_model": "businessai-chat", "businessai_api_key": SecretStr(KEY)}
    values.update(businessai_ledger_path=LEDGER_PATH, businessai_max_requests=1, businessai_token_budget=4096)
    for name, value in {**values, **changes}.items():
        monkeypatch.setattr(settings, name, value)


@respx.mock
async def test_success_sends_one_pinned_request_and_validates_existing_contract(caplog):
    caplog.set_level(logging.INFO, logger='app.ai.businessai')
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=response()))
    provider = BusinessAIProvider(configured())
    outcome = await process(request(), provider)
    assert outcome.metadata.status == "succeeded"
    assert outcome.output.insights.summary == RESULT["summary"]
    assert outcome.output.insights.action_items[0].task == "Send the report"
    assert outcome.metadata.model_id == "businessai-chat"
    assert route.call_count == 1
    sent = route.calls.last.request
    assert sent.method == "POST" and str(sent.url) == URL
    assert sent.headers["Authorization"] == f"Bearer {KEY}"
    payload = json.loads(sent.content)
    assert set(payload) == {"model", "messages", "max_tokens", "stream"}
    assert payload['max_tokens'] == 256 and payload['stream'] is False
    assert payload["model"] == "businessai-chat"
    assert payload["messages"][1] == {"role": "user", "content": f"[Speaker A] {TEXT}"}
    assert KEY not in repr(provider) + repr(configured()) + caplog.text
    assert TEXT not in caplog.text
    assert 'prompt_tokens=80 completion_tokens=40 total_tokens=120' in caplog.text
    with sqlite3.connect(LEDGER_PATH) as db:
        ledger = repr(db.execute('SELECT * FROM calls').fetchall())
    assert KEY not in ledger and TEXT not in ledger and RESULT['summary'] not in ledger


@pytest.mark.parametrize("data", [
    {}, {"choices": []}, {"choices": [{}, {}]},
    response(finish_reason="length"), response(finish_reason="content_filter"),
    {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
    response([]), response({}), response({"summary": " ", "action_items": []}),
    response({"summary": "s", "action_items": {}}),
    response({"summary": "s", "action_items": [{"action": " "}]}),
    response({"summary": "s", "action_items": [{"action": "Send", "source_quote": "invented"}]}),
    response({"summary": "s", "action_items": [{"action": "Send", "source_quote": TEXT,
                                               "assigned_to": "invented-person"}]}),
    response({"summary": "s", "action_items": [{"action": "Send", "source_quote": TEXT,
                                               "deadline_iso": "2099-01-01"}]}),
    response({**RESULT, "risks": ["out of scope"]}),
])
@respx.mock
async def test_invalid_output_is_safe_and_not_retried(data, caplog):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=data))
    with pytest.raises(ProviderFailure) as error:
        await BusinessAIProvider(configured()).process(request())
    assert error.value.code == FailureCode.INVALID_OUTPUT
    assert str(error.value) == "invalid_output"
    assert error.value.__suppress_context__
    assert route.call_count == 1
    assert KEY not in caplog.text and TEXT not in caplog.text


@respx.mock
async def test_invalid_response_json_is_rejected():
    route = respx.post(URL).mock(return_value=httpx.Response(200, text="PRIVATE body"))
    outcome = await process(request(), BusinessAIProvider(configured()))
    assert outcome.output is None
    assert outcome.metadata.failure.code == FailureCode.INVALID_OUTPUT
    assert not outcome.metadata.failure.retryable
    assert "PRIVATE" not in outcome.model_dump_json()
    assert route.call_count == 1


@pytest.mark.parametrize("status,code,retryable", [
    (401, FailureCode.CONFIGURATION, False), (403, FailureCode.CONFIGURATION, False),
    (429, FailureCode.RATE_LIMITED, True), (503, FailureCode.UNAVAILABLE, True),
    (500, FailureCode.UNAVAILABLE, True), (408, FailureCode.TIMEOUT, True),
    (504, FailureCode.TIMEOUT, True), (400, FailureCode.CONFIGURATION, False),
    (307, FailureCode.CONFIGURATION, False),
])
@respx.mock
async def test_http_failures_are_safe_single_attempts(status, code, retryable, caplog):
    route = respx.post(URL).mock(return_value=httpx.Response(
        status, text=f"PRIVATE {KEY} {TEXT}",
        headers={"Retry-After": "1", "Location": "https://other.invalid/chat"},
    ))
    outcome = await process(request(), BusinessAIProvider(configured()))
    assert outcome.output is None and outcome.metadata.failure.code == code
    assert outcome.metadata.failure.retryable == retryable
    assert route.call_count == 1 and len(respx.calls) == 1
    safe = outcome.model_dump_json() + caplog.text
    assert all(value not in safe for value in ("PRIVATE", KEY, TEXT))


@pytest.mark.parametrize("failure,code", [
    (httpx.ReadTimeout("PRIVATE timeout"), FailureCode.TIMEOUT),
    (httpx.ConnectTimeout("PRIVATE timeout"), FailureCode.TIMEOUT),
    (httpx.ConnectError("PRIVATE connection"), FailureCode.UNAVAILABLE),
])
@respx.mock
async def test_transport_failure_maps_safely_without_retry(failure, code):
    route = respx.post(URL).mock(side_effect=failure)
    outcome = await process(request(), BusinessAIProvider(configured()))
    assert outcome.output is None and outcome.metadata.failure.code == code
    assert "PRIVATE" not in outcome.model_dump_json()
    assert route.call_count == 1


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"chat_url": ""}, {"model_id": ""}, {"api_key": SecretStr("")},
    {"chat_url": "http://businessai.invalid/chat"},
    {"chat_url": "https://user:secret@businessai.invalid/chat"},
    {"chat_url": URL + "?key=secret"}, {"model_id": "invalid model name"},
])
def test_invalid_or_disabled_configuration_never_constructs_http_client(monkeypatch, changes):
    client = MagicMock(side_effect=AssertionError("HTTP client constructed"))
    monkeypatch.setattr(businessai.httpx, "AsyncClient", client)
    with pytest.raises(ProviderFailure) as error:
        BusinessAIProvider(configured(**changes))
    assert error.value.code == FailureCode.CONFIGURATION
    client.assert_not_called()


def test_default_config_is_disabled_and_registry_refuses_execution():
    config = BusinessAIConfig()
    registry, policy, requested = businessai_runtime_configuration(config)
    assert not config.enabled and not config.model_id and not config.chat_url
    assert config.max_requests == 0 and config.token_budget == 0
    with pytest.raises(ProviderRegistryError):
        registry.create(policy, requested_provider_id=requested, businessai_config=config)


def test_registry_requires_exact_explicit_configuration():
    config = configured()
    registry, policy, requested = businessai_runtime_configuration(config)
    with pytest.raises(ProviderRegistryError):
        registry.create(policy, requested_provider_id=requested)  # Descriptor alone is inert.
    with pytest.raises(ProviderRegistryError):
        registry.create(policy, requested_provider_id=requested,
                        businessai_config=configured(model_id="different-model"))
    assert registry.create(policy, requested_provider_id=requested,
                           businessai_config=config).identity.model_id == config.model_id


@respx.mock
async def test_bridge_persists_compatible_shape_and_does_not_call_legacy_factory(monkeypatch):
    from app.pipeline import extract

    runtime_settings(monkeypatch)
    monkeypatch.setattr(extract, "get_extractor", lambda: pytest.fail("Legacy factory called"))
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=response()))
    result = await bridge.extract_with_foundation(
        uuid4(), [TranscriptSegment("Speaker A", TEXT, 0, 1)], implementation="businessai",
    )
    assert result.summary == RESULT["summary"] and result.action_items[0].task == "Send the report"
    assert route.call_count == 1


@respx.mock
async def test_bridge_failure_never_falls_back_to_local_provider_or_another_model(monkeypatch):
    from app.ai.providers import LocalMockProvider, TranscriptOnlyProvider

    runtime_settings(monkeypatch)
    fallback = AsyncMock(side_effect=AssertionError("Fallback attempted"))
    monkeypatch.setattr(LocalMockProvider, "process", fallback)
    monkeypatch.setattr(TranscriptOnlyProvider, "process", fallback)
    route = respx.post(URL).mock(return_value=httpx.Response(503, text="PRIVATE body"))
    with pytest.raises(bridge.FoundationExtractionError) as error:
        await bridge.extract_with_foundation(
            uuid4(), [TranscriptSegment("Speaker A", TEXT, 0, 1)], implementation="businessai",
        )
    assert error.value.code == FailureCode.UNAVAILABLE
    assert "PRIVATE" not in str(error.value)
    assert route.call_count == 1 and len(respx.calls) == 1
    assert json.loads(route.calls.last.request.content)["model"] == "businessai-chat"
    fallback.assert_not_awaited()


@respx.mock
async def test_cancellation_propagates():
    calls = []

    async def cancelled(http_request):
        calls.append(http_request)
        raise asyncio.CancelledError

    respx.post(URL).mock(side_effect=cancelled)
    with pytest.raises(asyncio.CancelledError):
        await BusinessAIProvider(configured()).process(request())
    assert len(calls) == 1


@pytest.mark.parametrize('changes', [
    {'max_requests': 0}, {'token_budget': 0}, {'token_budget': 1},
    {'max_input_bytes': 1},
])
@respx.mock
async def test_admission_blocks_before_any_http(changes):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=response()))
    with pytest.raises(ProviderFailure):
        await BusinessAIProvider(configured(**changes)).process(request())
    assert route.call_count == 0


@respx.mock
async def test_ledger_survives_new_instances_and_blocks_duplicate_and_exhaustion():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=response()))
    req = request()
    await BusinessAIProvider(configured()).process(req)
    for next_request in (req, request()):
        with pytest.raises(ProviderFailure):
            await BusinessAIProvider(configured()).process(next_request)
    assert route.call_count == 1
    with sqlite3.connect(LEDGER_PATH) as db:
        row = db.execute('SELECT status,prompt_tokens,completion_tokens,total_tokens FROM calls').fetchone()
    assert row == ('reported', 80, 40, 120)


@respx.mock
async def test_duplicate_is_blocked_even_when_budget_remains():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=response()))
    req = request()
    config = configured(max_requests=5, token_budget=20000)
    await BusinessAIProvider(config).process(req)
    with pytest.raises(ProviderFailure):
        await BusinessAIProvider(config).process(req)
    await BusinessAIProvider(config).process(request())
    assert route.call_count == 2


@respx.mock
async def test_token_reservation_cap_blocks_a_second_different_request():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=response()))
    config = configured(max_requests=5, token_budget=2000)
    await BusinessAIProvider(config).process(request())
    with pytest.raises(ProviderFailure):
        await BusinessAIProvider(config).process(request())
    assert route.call_count == 1


@respx.mock
async def test_unwritable_ledger_fails_before_http(tmp_path):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=response()))
    config = configured(ledger_path=str(tmp_path / 'missing-parent' / 'usage.sqlite'))
    with pytest.raises(ProviderFailure) as error:
        await BusinessAIProvider(config).process(request())
    assert error.value.code == FailureCode.CONFIGURATION
    assert route.call_count == 0


@pytest.mark.parametrize('usage', [None, {}, {'prompt_tokens': True, 'completion_tokens': 1, 'total_tokens': 2},
    {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 9},
    {'prompt_tokens': 80, 'completion_tokens': 257, 'total_tokens': 337}])
@respx.mock
async def test_invalid_usage_or_overrun_locks_future_sends(usage):
    data = response(); data['usage'] = usage
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=data))
    config = configured(max_requests=5, token_budget=20000)
    with pytest.raises(ProviderFailure):
        await BusinessAIProvider(config).process(request())
    with pytest.raises(ProviderFailure):
        await BusinessAIProvider(config).process(request())
    assert route.call_count == 1


@respx.mock
async def test_timeout_retains_reservation_and_prevents_retry():
    req = request()
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout('PRIVATE'))
    for _ in range(2):
        with pytest.raises(ProviderFailure):
            await BusinessAIProvider(configured()).process(req)
    assert route.call_count == 1
    with sqlite3.connect(LEDGER_PATH) as db:
        assert db.execute('SELECT status FROM calls').fetchone() == ('reserved',)


@respx.mock
async def test_wall_clock_deadline_is_enforced():
    started = []
    async def delayed(_):
        started.append(True)
        await asyncio.sleep(0.1)
        return httpx.Response(200, json=response())
    route = respx.post(URL).mock(side_effect=delayed)
    outcome = await process(request(), BusinessAIProvider(configured(timeout_seconds=0.01)))
    assert outcome.metadata.failure.code == FailureCode.TIMEOUT
    assert started == [True]


def test_atomic_admission_across_concurrent_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.ai.businessai_budget import UsageLedger
    path = str(tmp_path / 'concurrent.sqlite')
    def reserve(i):
        try:
            UsageLedger(path).reserve(str(i), 100, max_requests=1, max_tokens=100)
            return True
        except ProviderFailure:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1


@respx.mock
async def test_synthetic_transcript_reaches_save_boundary_without_database_or_graph(monkeypatch):
    from app.services.ai_audit import audited_extraction
    from app.services import ai_audit
    runtime_settings(monkeypatch)
    events = []
    monkeypatch.setattr(ai_audit, 'add_audit_event', lambda db, **kw: events.append(kw))
    commit = AsyncMock()
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=response()))
    result = await audited_extraction(
        object(), meeting_id=uuid4(), job_id=None, lease_token=None, commit=commit,
        extract=bridge.extract_with_foundation,
        segments=[TranscriptSegment('Speaker A', TEXT, 0, 1)],
        implementation='businessai', known_participants=set(),
    )
    assert result.model_dump()['summary'] == RESULT['summary']
    assert result.action_items[0].source_quote == TEXT
    assert [e['outcome'] for e in events] == ['requested', 'succeeded']
    assert commit.await_count == 2 and route.call_count == 1


@respx.mock
async def test_invalid_output_never_reaches_save_boundary(monkeypatch):
    runtime_settings(monkeypatch)
    respx.post(URL).mock(return_value=httpx.Response(200, json=response({'summary':'x','action_items':[{'action':'invented','source_quote':'not spoken'}]})))
    with pytest.raises(bridge.FoundationExtractionError):
        await bridge.extract_with_foundation(uuid4(), [TranscriptSegment('Speaker A', TEXT, 0, 1)], implementation='businessai')
