"""One attempt per call. The existing recording worker remains the retry owner."""
import asyncio
import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from pydantic import ValidationError

from ..pipeline.extract import validate_extraction
from .contracts import Failure, FailureCode, ProcessingMetadata, ProcessingOutcome, ProcessingOutput, ProcessingRequest
from .providers import AIProvider, ProviderFailure


RETRYABLE = {FailureCode.TIMEOUT, FailureCode.RATE_LIMITED, FailureCode.UNAVAILABLE}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: int = 15
    max_delay_seconds: int = 300

    def __post_init__(self):
        if self.max_attempts < 1 or self.base_delay_seconds < 1 or self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("Invalid retry policy")

    def delay_after(self, metadata: ProcessingMetadata) -> int | None:
        if metadata.status != "failed" or not metadata.failure or not metadata.failure.retryable or metadata.attempt >= self.max_attempts:
            return None
        exponent = min(metadata.attempt - 1, self.max_delay_seconds.bit_length())
        return min(self.max_delay_seconds, self.base_delay_seconds * 2 ** exponent)


class ProcessingCancelled(asyncio.CancelledError):
    """Retain cancellation semantics while exposing safe attempt metadata."""
    def __init__(self, metadata: ProcessingMetadata):
        self.metadata = metadata
        super().__init__("AI processing cancelled")


def metadata_payload(existing: dict | None, metadata: ProcessingMetadata) -> dict:
    """Prepare an additive JSONB payload; never writes or commits database data.

    Latest attempt only, bounded in size. Durable history belongs in an explicitly
    designed audit/run store. The caller must use existing lease-fenced writes.
    """
    payload = deepcopy(existing or {})
    payload["ai_processing"] = metadata.model_dump(mode="json")
    return payload


def _validate_output(output: ProcessingOutput, request: ProcessingRequest) -> ProcessingOutput:
    output = ProcessingOutput.model_validate(output.model_dump())
    transcript = "\n".join(f"[{segment.speaker}] {segment.text}" for segment in request.segments)
    mode = output.insights.extraction_mode
    insights = validate_extraction(output.insights, transcript_only=mode == "transcript_only", transcript_text=transcript)
    if mode == "transcript_only" and (output.decisions or insights.summary or insights.action_items or insights.discussion_points or insights.risks or insights.deliverables or insights.next_steps or insights.speaker_highlights or insights.objective or insights.next_meeting):
        raise ValueError("Transcript-only output cannot contain generated insights")
    segments = {segment.id: segment for segment in request.segments}
    for decision in output.decisions:
        if not decision.text.strip() or not decision.source_quote.strip():
            raise ValueError("Decision requires text and evidence")
        if any(segment_id not in segments for segment_id in decision.source_segment_ids):
            raise ValueError("Unknown decision evidence segment")
        evidence = " ".join(segments[segment_id].text for segment_id in decision.source_segment_ids)
        if " ".join(decision.source_quote.split()).casefold() not in " ".join(evidence.split()).casefold():
            raise ValueError("Decision evidence does not match transcript")
    return output.model_copy(update={"insights": insights})


async def process(request: ProcessingRequest, provider: AIProvider, *, attempt: int = 1, timeout_seconds: float = 60) -> ProcessingOutcome:
    """Execute a single bounded attempt; do not persist, retry, or alter workflow.

    Unexpected exceptions are nonretryable by default. Cancellation propagates.
    Metadata contains hashes/identifiers, never transcript or exception content.
    """
    if attempt < 1 or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Attempt and timeout must be positive")
    request = ProcessingRequest.model_validate(request.model_dump())
    identity = provider.identity
    fingerprint = hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    started_at = datetime.now(timezone.utc)
    started = monotonic()
    run_id = uuid4()

    def metadata(status, failure=None):
        return ProcessingMetadata(run_id=run_id, meeting_id=request.meeting_id,
            input_fingerprint=fingerprint, provider_id=identity.provider_id,
            model_id=identity.model_id, prompt_version=identity.prompt_version,
            attempt=attempt, started_at=started_at, finished_at=datetime.now(timezone.utc),
            duration_ms=max(0, int((monotonic() - started) * 1000)), status=status, failure=failure)

    try:
        async with asyncio.timeout(timeout_seconds):
            output = await provider.process(request)
    except asyncio.CancelledError:
        raise ProcessingCancelled(metadata("cancelled")) from None
    except TimeoutError:
        code = FailureCode.TIMEOUT
    except ProviderFailure as error:
        code = error.code
    except ValidationError:
        code = FailureCode.INVALID_OUTPUT
    except Exception:
        code = FailureCode.UNKNOWN
    else:
        try:
            output = _validate_output(output, request)
        except (ValidationError, ValueError, AttributeError, TypeError):
            code = FailureCode.INVALID_OUTPUT
        else:
            return ProcessingOutcome(metadata=metadata("succeeded"), output=output)
    return ProcessingOutcome(metadata=metadata("failed", Failure(code=code, retryable=code in RETRYABLE)))
