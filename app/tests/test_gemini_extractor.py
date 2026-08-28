"""All HTTP responses are mocked; the session fixture forbids actual sockets."""
import json
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from app.pipeline import extract
from app.pipeline.transcribe import TranscriptSegment

SEGMENTS = [TranscriptSegment("Speaker A", "Review the report.", 0, 2)]
URL = "https://generativelanguage.googleapis.com/v1beta/models/offline-model:generateContent"


def configured(monkeypatch):
    monkeypatch.setattr(extract.settings, "gemini_api_key", "fake-offline-key")
    monkeypatch.setattr(extract.settings, "gemini_model", "offline-model")
    monkeypatch.setattr(extract.settings, "gemini_enabled", True)
    return extract.GeminiExtractor()


async def test_mock_is_stable_and_contains_all_review_sections():
    first = await extract.MockExtractor().extract(SEGMENTS)
    second = await extract.MockExtractor().extract(SEGMENTS)
    assert first.model_dump() == second.model_dump()
    assert first.summary and first.action_items and first.risks and first.next_steps
    assert first.speaker_highlights[0].key_points


@pytest.mark.parametrize("provider", [extract.MockExtractor, extract.TranscriptOnlyExtractor, extract.GeminiExtractor])
@pytest.mark.parametrize("segments", [[], [TranscriptSegment("A", "  ", 0, 1)]])
async def test_empty_transcript_is_rejected(provider, segments):
    with pytest.raises(ValueError, match="Transcript is empty"):
        await provider().extract(segments)


@pytest.mark.parametrize("field,value,message", [
    ("gemini_api_key", "", "GEMINI_API_KEY"),
    ("gemini_model", "", "GEMINI_MODEL"),
    ("gemini_model", "../unexpected?key=x", "GEMINI_MODEL"),
    ("gemini_enabled", False, "disabled"),
])
async def test_configuration_fails_before_constructing_http_client(monkeypatch, field, value, message):
    provider = configured(monkeypatch)
    monkeypatch.setattr(extract.settings, field, value)
    client = MagicMock(side_effect=AssertionError("No HTTP client allowed"))
    monkeypatch.setattr(extract.httpx, "AsyncClient", client)
    with pytest.raises(ValueError, match=message):
        await provider.extract(SEGMENTS)
    client.assert_not_called()


@respx.mock
async def test_gemini_uses_configured_model_and_validates_output(monkeypatch):
    provider = configured(monkeypatch)
    result = await extract.MockExtractor().extract(SEGMENTS)
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"candidates": [
        {"finishReason": "STOP", "content": {"parts": [{"text": result.model_dump_json()}]}}
    ]}))
    actual = await provider.extract(SEGMENTS)
    assert actual == result
    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == "fake-offline-key"
    assert "key=" not in str(request.url)
    payload = json.loads(request.content)
    assert "[Speaker A] Review the report." in payload["contents"][0]["parts"][0]["text"]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("data", [{}, {"candidates": []}, {"candidates": [
    {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}
]}, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": ""}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not JSON"}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]},
])
@respx.mock
async def test_gemini_empty_incomplete_invalid_output_fails(monkeypatch, data):
    provider = configured(monkeypatch)
    respx.post(URL).mock(return_value=httpx.Response(200, json=data))
    with pytest.raises(ValueError):
        await provider.extract(SEGMENTS)


@respx.mock
async def test_gemini_transport_failure_is_safe_and_propagated(monkeypatch):
    provider = configured(monkeypatch)
    respx.post(URL).mock(return_value=httpx.Response(429, text="sensitive provider body"))
    with pytest.raises(RuntimeError, match="Gemini transport request failed") as exc:
        await provider.extract(SEGMENTS)
    assert "fake-offline-key" not in str(exc.value) and "sensitive" not in str(exc.value)


@pytest.mark.parametrize("raw", ["", "  ", "not json", "[]", "null", "{}",
    '{"summary":" "}', '{"summary":"x","action_items":{}}',
    '{"summary":"x","action_items":[{"action":""}]}',
    '{"summary":"x","speaker_highlights":[{"key_points":42}]}',
    '{"summary":"x","extraction_mode":"transcript_only"}',
])
def test_invalid_structured_output_rejected(raw):
    with pytest.raises(ValueError):
        extract._parse_raw(raw)


def test_gemini_uses_existing_extractor_factory(monkeypatch):
    monkeypatch.setattr(extract.settings, "extractor_impl", "gemini")
    assert isinstance(extract.get_extractor(), extract.GeminiExtractor)
