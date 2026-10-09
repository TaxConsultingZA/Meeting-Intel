"""Local-only bridge checks; the shared test fixture prohibits network access."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.ai import runtime_bridge as bridge
from app.ai.contracts import Decision, FailureCode, ProcessingOutput
from app.ai.processing import ProcessingCancelled
from app.ai.providers import ProviderFailure, ProviderIdentity
from app.ai.policy import ProcessingPolicy, ProviderCapabilities, RouteKind
from app.ai.providers import ProviderDescriptor
from app.ai.registry import ProviderRegistry, local_runtime_configuration
from app.pipeline import extract
from app.pipeline.transcribe import TranscriptSegment
from app.schemas import ExtractedActionItem, RichExtractionResult


def segments():
    return [TranscriptSegment("Speaker A", "Please send the report.", 2, 5)]


def inject(monkeypatch, *, output=None, error=None):
    provider = SimpleNamespace(identity=ProviderIdentity("test.local"),
        process=AsyncMock(side_effect=error, return_value=output))
    monkeypatch.setattr(bridge, "get_local_provider", lambda _: provider)
    return provider


async def test_success_uses_foundation_request_and_existing_result_schema(monkeypatch):
    local = bridge.LocalMockProvider()
    provider = inject(monkeypatch)
    provider.process.side_effect = local.process
    meeting_id = uuid4()
    source = segments()
    result = await bridge.extract_with_foundation(meeting_id, source, implementation="mock")
    assert isinstance(result, RichExtractionResult)
    assert result.summary and result.action_items[0].source_quote == source[0].text
    request = provider.process.await_args.args[0]
    assert request.meeting_id == meeting_id
    assert request.segments[0].id == "segment-0"
    assert request.segments[0].start == 2 and request.segments[0].end == 5
    provider.process.assert_awaited_once()


async def test_transcript_only_remains_empty_and_does_not_instantiate_legacy_factory(monkeypatch):
    monkeypatch.setattr(extract, "get_extractor", lambda: pytest.fail("Legacy factory invoked"))
    result = await bridge.extract_with_foundation(uuid4(), segments(), implementation="transcript_only")
    assert result.extraction_mode == "transcript_only"
    assert not result.summary and not result.action_items


@pytest.mark.parametrize("implementation", ["gemini", "azure_openai", "businessai", "unknown"])
async def test_external_or_unknown_selection_fails_before_factory_or_processing(monkeypatch, implementation):
    monkeypatch.setattr(extract, "get_extractor", lambda: pytest.fail("Legacy factory invoked"))
    runner = AsyncMock()
    monkeypatch.setattr(bridge, "process", runner)
    with pytest.raises(bridge.FoundationExtractionError) as exc:
        await bridge.extract_with_foundation(uuid4(), segments(), implementation=implementation)
    assert exc.value.code == FailureCode.CONFIGURATION
    runner.assert_not_awaited()


@pytest.mark.parametrize("error,code", [
    (RuntimeError("private upstream response"), FailureCode.UNKNOWN),
    (ProviderFailure(FailureCode.UNAVAILABLE), FailureCode.UNAVAILABLE),
    (TimeoutError("private timeout"), FailureCode.TIMEOUT),
])
async def test_failed_processing_is_safe_and_makes_one_attempt(monkeypatch, error, code):
    provider = inject(monkeypatch, error=error)
    with pytest.raises(bridge.FoundationExtractionError) as exc:
        await bridge.extract_with_foundation(uuid4(), segments(), implementation="mock")
    assert exc.value.code == code and "private" not in str(exc.value)
    provider.process.assert_awaited_once()


@pytest.mark.parametrize("output", [
    {"summary": "invalid contract"},
    ProcessingOutput(insights=RichExtractionResult(summary="")),
    ProcessingOutput(insights=RichExtractionResult(summary="Summary", action_items=[
        ExtractedActionItem(action="Send report", source_quote="Words absent from transcript")
    ])),
    ProcessingOutput(insights=RichExtractionResult(summary="Summary", next_steps=["Unsupported"])),
    ProcessingOutput(insights=RichExtractionResult(summary="Summary"), decisions=(Decision(
        text="Send report", status="agreed", source_segment_ids=("segment-0",),
        source_quote="Please send the report.",
    ),)),
    ProcessingOutput(insights=RichExtractionResult(extraction_mode="transcript_only", summary="Invented")),
])
async def test_invalid_or_out_of_scope_output_is_rejected(monkeypatch, output):
    provider = inject(monkeypatch, output=output)
    with pytest.raises(bridge.FoundationExtractionError) as exc:
        await bridge.extract_with_foundation(uuid4(), segments(), implementation="mock")
    assert exc.value.code == FailureCode.INVALID_OUTPUT
    provider.process.assert_awaited_once()


async def test_known_participant_validation_still_applies(monkeypatch):
    inject(monkeypatch, output=ProcessingOutput(insights=RichExtractionResult(
        summary="Summary", action_items=[ExtractedActionItem(
            action="Send report", assigned_to="outsider@example.test",
            source_quote="outsider@example.test will send the report.",
        )],
    )))
    with pytest.raises(bridge.FoundationExtractionError) as exc:
        await bridge.extract_with_foundation(uuid4(), [TranscriptSegment(
            "Speaker A", "outsider@example.test will send the report.", 0, 1,
        )], implementation="mock", known_participants={"owner@example.test"})
    assert exc.value.code == FailureCode.INVALID_OUTPUT


async def test_saved_plain_text_fallback_does_not_invent_timestamps(monkeypatch):
    provider = inject(monkeypatch, output=ProcessingOutput(
        insights=RichExtractionResult(extraction_mode="transcript_only")))
    await bridge.extract_with_foundation(uuid4(), segments(), implementation="transcript_only",
                                         timestamps_available=False)
    segment = provider.process.await_args.args[0].segments[0]
    assert segment.start is None and segment.end is None


async def test_empty_segments_are_skipped_without_changing_source(monkeypatch):
    provider = inject(monkeypatch, output=ProcessingOutput(
        insights=RichExtractionResult(extraction_mode="transcript_only")))
    source = [TranscriptSegment("Speaker A", " ", 0, 1), *segments()]
    await bridge.extract_with_foundation(uuid4(), source, implementation="transcript_only")
    assert len(source) == 2 and source[0].text == " "
    assert len(provider.process.await_args.args[0].segments) == 1
    assert provider.process.await_args.args[0].segments[0].id == "segment-1"


async def test_cancellation_propagates_instead_of_becoming_failure(monkeypatch):
    started = asyncio.Event()
    async def waiting(request):
        started.set()
        await asyncio.Event().wait()
    provider = inject(monkeypatch)
    provider.process.side_effect = waiting
    task = asyncio.create_task(bridge.extract_with_foundation(uuid4(), segments(), implementation="mock"))
    await started.wait()
    task.cancel()
    with pytest.raises(ProcessingCancelled):
        await task
    provider.process.assert_awaited_once()


async def test_runtime_registry_policy_denial_stops_before_processing(monkeypatch):
    prepared, _, requested = local_runtime_configuration("mock")
    monkeypatch.setattr(bridge, "local_runtime_configuration", lambda _: (
        prepared, ProcessingPolicy(), requested))
    runner = AsyncMock()
    monkeypatch.setattr(bridge, "process", runner)
    with pytest.raises(bridge.FoundationExtractionError) as exc:
        await bridge.extract_with_foundation(uuid4(), segments(), implementation="mock")
    assert exc.value.code == FailureCode.CONFIGURATION
    runner.assert_not_awaited()


async def test_runtime_disabled_route_stops_before_processing(monkeypatch):
    _, configured, requested = local_runtime_configuration("mock")
    prepared = ProviderRegistry((ProviderDescriptor(capabilities=ProviderCapabilities(
        provider_id=requested, route_kind=RouteKind.LOCAL_MOCK,
        enabled=False, approved=True, contract_versions=frozenset({"1.0"}),
        features=configured.required_features,
    ), local_factory="mock"),))
    monkeypatch.setattr(bridge, "local_runtime_configuration", lambda _: (prepared, configured, requested))
    runner = AsyncMock()
    monkeypatch.setattr(bridge, "process", runner)
    with pytest.raises(bridge.FoundationExtractionError):
        await bridge.extract_with_foundation(uuid4(), segments(), implementation="mock")
    runner.assert_not_awaited()


async def test_local_failure_does_not_log_transcript_or_raw_response(monkeypatch, caplog):
    inject(monkeypatch, error=RuntimeError("private response body"))
    with pytest.raises(bridge.FoundationExtractionError) as exc:
        await bridge.extract_with_foundation(uuid4(), segments(), implementation="mock")
    assert "private response body" not in str(exc.value)
    assert "private response body" not in caplog.text
    assert segments()[0].text not in caplog.text


async def test_invalid_response_from_registry_constructed_provider_is_rejected(monkeypatch):
    response = AsyncMock(return_value={"summary": "invalid foundation response"})
    monkeypatch.setattr(bridge.LocalMockProvider, "process", response)
    with pytest.raises(bridge.FoundationExtractionError) as exc:
        await bridge.extract_with_foundation(uuid4(), segments(), implementation="mock")
    assert exc.value.code == FailureCode.INVALID_OUTPUT
    response.assert_awaited_once()


async def test_processing_failure_does_not_fall_back_to_other_local_provider(monkeypatch):
    from app.ai.providers import TranscriptOnlyProvider
    failed = AsyncMock(side_effect=RuntimeError("private provider response"))
    fallback = AsyncMock()
    monkeypatch.setattr(bridge.LocalMockProvider, "process", failed)
    monkeypatch.setattr(TranscriptOnlyProvider, "process", fallback)
    with pytest.raises(bridge.FoundationExtractionError):
        await bridge.extract_with_foundation(uuid4(), segments(), implementation="mock")
    failed.assert_awaited_once()
    fallback.assert_not_awaited()
