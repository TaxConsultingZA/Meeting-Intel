"""All providers here are local; the shared fixture prohibits network access."""
import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.contracts import Decision, FailureCode, ProcessingOutput, ProcessingRequest, Segment
from app.ai.processing import ProcessingCancelled, RetryPolicy, metadata_payload, process
from app.ai.providers import ProviderFailure, ProviderIdentity, TranscriptOnlyProvider
from app.schemas import RichExtractionResult


def request():
    return ProcessingRequest(meeting_id=uuid4(), segments=(Segment(id="s1", speaker="Speaker A", text="We agreed to release on Friday.", start=0, end=5),))


class LocalProvider:
    identity = ProviderIdentity("test.local", "test-model", "prompt-v1")

    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = 0

    async def process(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return self.output


def output(**kwargs):
    return ProcessingOutput(insights=RichExtractionResult(summary="Release discussed."), **kwargs)


@pytest.mark.parametrize("changes", [{"contract_version": "2.0"}, {"segments": []}, {"unexpected": "field"}])
def test_request_rejects_unsupported_or_invalid_contract(changes):
    data = request().model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        ProcessingRequest.model_validate(data)


@pytest.mark.parametrize("changes", [{"text": " "}, {"start": 5, "end": 1}, {"start": None, "end": 1}, {"start": float("inf")}])
def test_invalid_segment_rejected(changes):
    data = request().segments[0].model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        Segment.model_validate(data)


def test_duplicate_segment_ids_rejected():
    segment = request().segments[0]
    with pytest.raises(ValidationError):
        ProcessingRequest(meeting_id=uuid4(), segments=(segment, segment))


async def test_local_transcript_only_has_no_invented_insights_and_stable_hash():
    source = request()
    before = source.model_dump_json()
    first = await process(source, TranscriptOnlyProvider())
    second = await process(source, TranscriptOnlyProvider())
    assert first.output.insights.extraction_mode == "transcript_only"
    assert not first.output.insights.summary and not first.output.decisions
    assert first.metadata.status == "succeeded"
    assert first.metadata.input_fingerprint == second.metadata.input_fingerprint
    assert first.metadata.run_id != second.metadata.run_id
    assert source.model_dump_json() == before
    assert source.segments[0].text not in first.metadata.model_dump_json()


async def test_metadata_merge_preserves_transcript_results_and_does_not_mutate_source():
    outcome = await process(request(), TranscriptOnlyProvider())
    original = {"raw_transcript": "saved", "summary": "human work", "nested": {"value": 1}}
    merged = metadata_payload(original, outcome.metadata)
    assert merged["raw_transcript"] == "saved" and merged["summary"] == "human work"
    assert merged["ai_processing"]["contract_version"] == "1.0"
    assert "ai_processing" not in original
    merged["nested"]["value"] = 2
    assert original["nested"]["value"] == 1


async def test_valid_structured_output_with_decision_evidence():
    result = output(decisions=(Decision(text="Release Friday", status="agreed", source_segment_ids=("s1",), source_quote="We agreed to release on Friday."),))
    outcome = await process(request(), LocalProvider(result))
    assert outcome.metadata.status == "succeeded"
    assert outcome.metadata.model_id == "test-model"
    assert outcome.metadata.prompt_version == "prompt-v1"
    assert outcome.output.decisions[0].status == "agreed"


@pytest.mark.parametrize("result", [
    output(decisions=(Decision(text="Invented", status="agreed", source_segment_ids=("s2",), source_quote="We agreed"),)),
    output(decisions=(Decision(text="Invented", status="agreed", source_segment_ids=("s1",), source_quote="Hire everyone"),)),
    ProcessingOutput(insights=RichExtractionResult(summary="")),
    ProcessingOutput(insights=RichExtractionResult(extraction_mode="transcript_only", summary="invented")),
    None,
])
async def test_invalid_output_is_not_retryable_and_never_returned(result):
    outcome = await process(request(), LocalProvider(result))
    assert outcome.output is None
    assert outcome.metadata.failure.code == FailureCode.INVALID_OUTPUT
    assert RetryPolicy().delay_after(outcome.metadata) is None


@pytest.mark.parametrize("code", list(FailureCode))
async def test_failure_classification_and_retry_advice_do_not_execute_retry(code):
    provider = LocalProvider(error=ProviderFailure(code))
    outcome = await process(request(), provider)
    assert outcome.metadata.status == "failed" and outcome.output is None
    expected = code in {FailureCode.TIMEOUT, FailureCode.UNAVAILABLE, FailureCode.RATE_LIMITED}
    assert outcome.metadata.failure.retryable == expected
    assert RetryPolicy().delay_after(outcome.metadata) == (15 if expected else None)
    assert provider.calls == 1
    exhausted = outcome.metadata.model_copy(update={"attempt": 3})
    assert RetryPolicy().delay_after(exhausted) is None


async def test_unknown_failure_does_not_leak_sensitive_error_or_retry():
    outcome = await process(request(), LocalProvider(error=RuntimeError("secret-token private transcript")))
    assert outcome.metadata.failure.code == FailureCode.UNKNOWN
    assert "secret-token" not in outcome.model_dump_json()
    assert not outcome.metadata.failure.retryable


async def test_timeout_is_bounded_and_retryable():
    class Slow(LocalProvider):
        async def process(self, request):
            await asyncio.Event().wait()
    outcome = await process(request(), Slow(), timeout_seconds=0.01)
    assert outcome.metadata.failure.code == FailureCode.TIMEOUT


async def test_cancellation_propagates_with_metadata():
    class Slow(LocalProvider):
        async def process(self, request):
            await asyncio.Event().wait()
    task = asyncio.create_task(process(request(), Slow()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(ProcessingCancelled) as cancelled:
        await task
    assert cancelled.value.metadata.status == "cancelled"
    assert RetryPolicy().delay_after(cancelled.value.metadata) is None


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
async def test_invalid_timeout_does_not_invoke_provider(timeout):
    provider = LocalProvider(output())
    with pytest.raises(ValueError):
        await process(request(), provider, timeout_seconds=timeout)
    assert provider.calls == 0


async def test_retry_delay_is_capped():
    outcome = await process(request(), LocalProvider(error=ProviderFailure(FailureCode.UNAVAILABLE)), attempt=100)
    assert RetryPolicy(max_attempts=101).delay_after(outcome.metadata) == 300
