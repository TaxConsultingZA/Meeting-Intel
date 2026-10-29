"""Foundation entry point at the existing extraction boundary.

No persistence, retries, transport or authorization: those remain with callers.
"""
from uuid import UUID

from ..config import get_settings
from ..pipeline.extract import require_transcript, validate_extraction
from ..pipeline.transcribe import TranscriptSegment
from ..schemas import RichExtractionResult
from .contracts import FailureCode, ProcessingOutput, ProcessingRequest, Segment
from .processing import process
from .providers import AIProvider, ProviderFailure
from .providers import LocalMockProvider  # noqa: F401 - existing bridge test seam
from .businessai import BusinessAIConfig
from .registry import ProviderRegistryError, businessai_runtime_configuration, local_runtime_configuration


class FoundationExtractionError(RuntimeError):
    """Safe failure category; the existing worker owns retry decisions."""

    def __init__(self, code: FailureCode):
        self.code = code
        super().__init__(f"AI foundation processing failed: {code.value}")


def get_local_provider(implementation: str) -> AIProvider:
    # Keep the bridge entry point/test seam, but enforce registry/policy selection.
    # LocalMockProvider remains imported here for existing local test compatibility.
    try:
        if implementation == "businessai":
            settings = get_settings()
            config = BusinessAIConfig(
                enabled=settings.businessai_enabled, chat_url=settings.businessai_chat_url,
                model_id=settings.businessai_model, api_key=settings.businessai_api_key,
                max_output_tokens=settings.businessai_max_output_tokens,
                max_input_bytes=settings.businessai_max_input_bytes,
                timeout_seconds=settings.businessai_timeout_seconds,
                max_requests=settings.businessai_max_requests,
                token_budget=settings.businessai_token_budget,
                ledger_path=settings.businessai_ledger_path,
            )
            registry, policy, requested_id = businessai_runtime_configuration(config)
            return registry.create(policy, requested_provider_id=requested_id, businessai_config=config)
        registry, policy, requested_id = local_runtime_configuration(implementation)
        return registry.create(policy, requested_provider_id=requested_id)
    except ProviderRegistryError:
        raise FoundationExtractionError(FailureCode.CONFIGURATION) from None


class _SummaryActionsOnly:
    """Enforce this phase's output scope inside foundation validation."""

    def __init__(self, provider: AIProvider):
        self.provider = provider
        self.identity = provider.identity

    async def process(self, request: ProcessingRequest) -> ProcessingOutput:
        output = await self.provider.process(request)
        if not isinstance(output, ProcessingOutput):
            raise ProviderFailure(FailureCode.INVALID_OUTPUT)
        output = ProcessingOutput.model_validate(output.model_dump())
        values = output.insights.model_dump()
        defaults = RichExtractionResult().model_dump()
        if output.decisions or any(
            value != defaults[key]
            for key, value in values.items()
            if key not in {"summary", "action_items", "extraction_mode"}
        ):
            raise ProviderFailure(FailureCode.INVALID_OUTPUT)
        return output


async def extract_with_foundation(
    meeting_id: UUID,
    segments: list[TranscriptSegment],
    *,
    implementation: str,
    known_participants: set[str] | None = None,
    timestamps_available: bool = True,
) -> RichExtractionResult:
    """Run one explicit attempt; return only validated, review-compatible output.

    Failure raises before the caller can write results. Cancellation propagates.
    Metadata is currently ephemeral; no additional database writes are made.
    Missing timestamps stay null, including the saved plain-text retry fallback.
    """
    provider = get_local_provider(implementation)
    require_transcript(segments)
    request = ProcessingRequest(meeting_id=meeting_id, segments=tuple(
        Segment(
            id=f"segment-{index}", speaker=segment.speaker, text=segment.text,
            start=segment.start if timestamps_available else None,
            end=segment.end if timestamps_available else None,
        )
        for index, segment in enumerate(segments)
        if segment.text.strip()
    ))
    outcome = await process(request, _SummaryActionsOnly(provider))
    if outcome.metadata.status != "succeeded" or outcome.output is None:
        code = outcome.metadata.failure.code if outcome.metadata.failure else FailureCode.UNKNOWN
        raise FoundationExtractionError(code)
    try:
        return validate_extraction(
            outcome.output.insights,
            transcript_only=implementation == "transcript_only",
            transcript_text="\n".join(f"[{s.speaker}] {s.text}" for s in segments),
            known_participants=known_participants,
        )
    except ValueError:
        raise FoundationExtractionError(FailureCode.INVALID_OUTPUT) from None
