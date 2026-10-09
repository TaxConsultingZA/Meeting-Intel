"""Versioned application contracts, independent of vendor transport formats."""
from enum import Enum
from typing import Literal
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..schemas import RichExtractionResult


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Segment(Contract):
    id: str = Field(min_length=1)
    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)
    start: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_segment(self):
        if not self.text.strip():
            raise ValueError("Transcript segment must contain text")
        if (self.start is None) != (self.end is None):
            raise ValueError("Provide both timestamps or neither")
        if self.start is not None and self.end < self.start:
            raise ValueError("Segment end precedes start")
        return self


class ProcessingRequest(Contract):
    contract_version: Literal["1.0"] = "1.0"
    meeting_id: UUID
    segments: tuple[Segment, ...] = Field(min_length=1)
    language: str | None = None

    @model_validator(mode="after")
    def unique_segments(self):
        if len({segment.id for segment in self.segments}) != len(self.segments):
            raise ValueError("Segment IDs must be unique")
        return self


class Decision(Contract):
    text: str = Field(min_length=1)
    status: Literal["agreed", "proposed", "unresolved"]
    source_segment_ids: tuple[str, ...] = Field(min_length=1)
    source_quote: str = Field(min_length=1)


class ProcessingOutput(Contract):
    contract_version: Literal["1.0"] = "1.0"
    insights: RichExtractionResult
    decisions: tuple[Decision, ...] = ()


class FailureCode(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    CONFIGURATION = "configuration"
    INVALID_OUTPUT = "invalid_output"
    UNKNOWN = "unknown"


class Failure(Contract):
    code: FailureCode
    retryable: bool


class ProcessingMetadata(Contract):
    contract_version: Literal["1.0"] = "1.0"
    run_id: UUID
    meeting_id: UUID
    input_fingerprint: str
    provider_id: str
    model_id: str | None = None
    prompt_version: str | None = None
    attempt: int = Field(ge=1)
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0)
    status: Literal["succeeded", "failed", "cancelled"]
    failure: Failure | None = None


class ProcessingOutcome(Contract):
    metadata: ProcessingMetadata
    output: ProcessingOutput | None = None
