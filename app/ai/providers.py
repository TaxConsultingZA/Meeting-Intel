"""Explicit injection only: no factory that can enable an external provider."""
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field, model_validator

from ..schemas import ExtractedActionItem, RichExtractionResult
from .contracts import Contract, FailureCode, ProcessingOutput, ProcessingRequest
from .policy import ProviderCapabilities, RouteKind


@dataclass(frozen=True)
class ProviderIdentity:
    provider_id: str
    model_id: str | None = None
    prompt_version: str | None = None


class AIProvider(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    async def process(self, request: ProcessingRequest) -> ProcessingOutput: ...


class ProviderFailure(Exception):
    """Adapters translate vendor failures to safe codes, never raw responses."""
    def __init__(self, code: FailureCode):
        self.code = code
        super().__init__(code.value)


class TranscriptOnlyProvider:
    identity = ProviderIdentity("local.transcript_only")

    async def process(self, request: ProcessingRequest) -> ProcessingOutput:
        return ProcessingOutput(insights=RichExtractionResult(extraction_mode="transcript_only"))


class LocalMockProvider:
    """Deterministic test output, not a language model or semantic extractor."""

    identity = ProviderIdentity("local.mock")

    async def process(self, request: ProcessingRequest) -> ProcessingOutput:
        text = request.segments[0].text.strip()
        return ProcessingOutput(insights=RichExtractionResult(
            summary=f"Local mock summary: {text}",
            action_items=[ExtractedActionItem(action=text, source_quote=text)],
        ))


class ProviderDescriptor(Contract):
    """Server-owned adapter preparation; never a transport or credential value.

    Cloud/workspace descriptors are inert, even when policy permits selection.
    Credential references name future server-side bindings and are never read.
    Only the two reviewed local implementations have executable factory keys.
    """

    capabilities: ProviderCapabilities
    model_id: str | None = Field(default=None, min_length=1)
    prompt_version: str | None = Field(default=None, min_length=1)
    credential_reference: str | None = Field(
        default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$", repr=False, exclude=True,
    )
    local_factory: Literal["transcript_only", "mock"] | None = None

    @model_validator(mode="after")
    def valid_preparation(self):
        kind = self.capabilities.route_kind
        local_kind = kind in {RouteKind.LOCAL_TRANSCRIPT, RouteKind.LOCAL_MOCK}
        if not local_kind and self.local_factory is not None:
            raise ValueError("External preparations cannot bind an executable factory")
        if local_kind:
            expected = "transcript_only" if kind == RouteKind.LOCAL_TRANSCRIPT else "mock"
            if self.local_factory is not None and self.local_factory != expected:
                raise ValueError("Local factory must match its route kind")
            if any(value is not None for value in (
                self.model_id, self.prompt_version, self.credential_reference,
            )):
                raise ValueError("Local providers do not accept external adapter configuration")
        if any(value is not None and not value.strip() for value in (
            self.model_id, self.prompt_version,
        )):
            raise ValueError("Adapter identifiers must not be blank")
        return self
