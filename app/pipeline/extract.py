import json
import re
import httpx
from abc import ABC, abstractmethod
from ..config import get_settings
from ..schemas import RichExtractionResult, ExtractedActionItem
from ..models import Confidence
from .transcribe import TranscriptSegment

settings = get_settings()


SYSTEM_PROMPT = """You are a meeting intelligence assistant for Tax Consulting SA, a professional tax advisory firm.
Analyse the full transcript and return ONLY valid JSON — no prose, no markdown fences.

Extract every section as completely as possible from what was actually said.
If a section has no content, return an empty list or null — never invent information.

IMPORTANT RULES:
- Be concise. Each field value should be 1-2 sentences max. Bullet points max 2 per speaker.
- discussion_points: capture EVERY topic raised by ANY speaker, no matter how brief.
  Even a single sentence from one speaker that raises a point, states an opinion,
  or clarifies a responsibility counts as a discussion point. Do not omit any speaker's contribution.
- speaker_highlights: for EVERY speaker who appears in the transcript, summarise their
  most important contributions in at most 2 bullet points. Use the speaker label
  (e.g. "Speaker A") if no real name is known.

Return this exact schema:
{
  "objective": "<1-2 sentence purpose of the meeting>",
  "meeting_time": "<time mentioned in the meeting or null>",
  "attendees": ["<name or Speaker label>"],
  "apologies": ["<anyone mentioned as absent>"],
  "platform": "<Microsoft Teams | In-Person | Hybrid | other>",
  "speaker_highlights": [
    {
      "speaker": "<Speaker A | real name if known>",
      "role": "<inferred role e.g. Facilitator, Participant, or null>",
      "key_points": [
        "<most important thing this speaker said or contributed>",
        "<second key point if applicable>"
      ]
    }
  ],
  "discussion_points": [
    {
      "topic": "<topic heading — even one-line topics count>",
      "summary": "<what was said, by whom, including ALL speaker contributions on this topic>",
      "outcome": "<decision, conclusion, or unresolved — never leave blank if something was said>"
    }
  ],
  "action_items": [
    {
      "action": "<specific task to be completed>",
      "assigned_to": "<person responsible>",
      "department": "<team or department if mentioned, else null>",
      "reason": "<why this action is needed>",
      "expected_outcome": "<what success looks like>",
      "due_date": "<date as spoken, e.g. 'end of June' or null>",
      "confidence": "high|medium|low",
      "source_quote": "<exact words from transcript>"
    }
  ],
  "deliverables": [
    {
      "deliverable": "<document, report, or output to be produced>",
      "responsible": "<person responsible>",
      "delivery_method": "<email | SharePoint | Teams | other>",
      "due_date": "<date as spoken or null>",
      "expected_outcome": "<what the deliverable achieves>"
    }
  ],
  "risks": [
    {
      "item": "<risk or challenge identified>",
      "impact": "<potential consequence>",
      "resolution": "<proposed solution or support needed>",
      "owner": "<person responsible for resolving>"
    }
  ],
  "next_steps": ["<bullet point next step>"],
  "next_meeting": {
    "proposed_date": "<date mentioned or null>",
    "proposed_time": "<time mentioned or null>",
    "agenda_focus": "<topics for next meeting or null>"
  },
  "summary": "<2-4 sentence overall meeting summary>"
}"""


def _transcript_to_text(segs: list[TranscriptSegment]) -> str:
    """Flatten diarized segments into a single ``[Speaker X] text`` string for the LLM prompt."""
    return "\n".join(f"[{s.speaker}] {s.text}" for s in segs)


def _parse_raw(raw: str) -> RichExtractionResult:
    """Parse the LLM's raw JSON string into a RichExtractionResult.

    Strips markdown code fences (`` ```json ... ``` ``) that some models add
    even when instructed not to, then deserialises and maps to the schema.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Extractor returned an empty response")
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    if not isinstance(data, dict):
        raise ValueError("Extractor response must be a JSON object")
    # The prompt permits null for empty sections, not arbitrary falsy values.
    for name in ("attendees", "apologies", "speaker_highlights", "discussion_points",
                 "action_items", "deliverables", "risks", "next_steps"):
        if data.get(name, []) is None:
            data[name] = []
    return validate_extraction(data)


def require_transcript(segments: list[TranscriptSegment]) -> None:
    if not segments or not any(s.text.strip() for s in segments):
        raise ValueError("Transcript is empty; extraction cannot proceed")


def validate_extraction(value, *, transcript_only: bool = False) -> RichExtractionResult:
    # Revalidate even model instances returned by adapters (including test doubles).
    if isinstance(value, RichExtractionResult):
        value = value.model_dump()
    result = RichExtractionResult.model_validate(value)
    expected_mode = "transcript_only" if transcript_only else "structured"
    if result.extraction_mode != expected_mode:
        raise ValueError("Unexpected extraction mode")
    if not transcript_only and not result.summary.strip():
        raise ValueError("Structured extraction requires a nonempty summary")
    if any(not (item.action or item.task).strip() for item in result.action_items):
        raise ValueError("Extracted action items require nonempty task text")
    return result


class Extractor(ABC):
    """Abstract base class for all AI extraction backends."""

    @abstractmethod
    async def extract(self, segments: list[TranscriptSegment]) -> RichExtractionResult:
        """Extract structured meeting intelligence from transcript segments."""
        ...


class MockExtractor(Extractor):
    """Stub extractor that returns hard-coded results — used in local dev/tests."""

    async def extract(self, segments: list[TranscriptSegment]) -> RichExtractionResult:
        require_transcript(segments)
        return RichExtractionResult(
            objective="To review the SARS compliance report and confirm client numbers.",
            attendees=["Speaker A", "Speaker B", "Sarah"],
            platform="Microsoft Teams",
            speaker_highlights=[
                {"speaker": "Speaker A", "key_points": ["Requested the compliance report and confirmed ownership."]},
                {"speaker": "Speaker B", "key_points": ["Plans to finish the report in early June."]},
            ],
            discussion_points=[
                {"topic": "SARS Compliance Report", "summary": "Speaker B to finalise the report by early June.", "outcome": "Report deadline confirmed."},
            ],
            action_items=[
                ExtractedActionItem(
                    action="Finalise SARS compliance report",
                    assigned_to="Speaker B", department=None,
                    reason="Required for client submission",
                    expected_outcome="Report submitted to SARS on time",
                    due_date="early June", confidence=Confidence.medium,
                    source_quote="Sure, I'll try wrap that up early June.",
                ),
                ExtractedActionItem(
                    action="Confirm client numbers",
                    assigned_to="Sarah", department=None,
                    reason="Numbers needed before report can be finalised",
                    expected_outcome="Accurate client count confirmed",
                    due_date=None, confidence=Confidence.low,
                    source_quote="Sarah, can you confirm the client numbers?",
                ),
            ],
            deliverables=[],
            risks=[{"item": "Client numbers are unconfirmed", "impact": "Report completion may be delayed",
                    "resolution": "Confirm the numbers before finalising", "owner": "Sarah"}],
            next_steps=["Sarah to send client numbers by end of week.", "Speaker B to circulate draft report for review."],
            next_meeting=None,
            summary="Team discussed the SARS compliance report and client number confirmation.",
        )


class TranscriptOnlyExtractor(Extractor):
    """Complete processing without calling a paid language model.

    AssemblyAI's real transcript remains on the meeting record. Structured
    notes stay empty until the company selects a replacement AI provider.
    """

    async def extract(self, segments: list[TranscriptSegment]) -> RichExtractionResult:
        require_transcript(segments)
        return RichExtractionResult(extraction_mode="transcript_only")


class AzureOpenAIExtractor(Extractor):
    """Single-pass extractor using Azure OpenAI (GPT-4o by default).

    Uses ``response_format=json_object`` so the model is constrained to valid JSON.
    """

    async def extract(self, segments: list[TranscriptSegment]) -> RichExtractionResult:
        require_transcript(segments)
        from openai import AsyncAzureOpenAI
        client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_key,
            api_version="2024-02-01",
        )
        resp = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _transcript_to_text(segments)},
            ],
        )
        return _parse_raw(resp.choices[0].message.content)


class GeminiExtractor(Extractor):
    """Opt-in REST adapter; no SDK, network call at import, or default model.

    Transport is mocked in all tests. Live API/model compatibility and company
    authorisation still require administrator verification before enabling.
    """

    async def extract(self, segments: list[TranscriptSegment]) -> RichExtractionResult:
        require_transcript(segments)
        if not settings.gemini_api_key.strip():
            raise ValueError("GEMINI_API_KEY is required for the Gemini extractor")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", settings.gemini_model):
            raise ValueError("GEMINI_MODEL must be an explicitly configured model name")
        if not settings.gemini_enabled:
            raise ValueError("Gemini requests are disabled; GEMINI_ENABLED requires explicit authorisation")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
                    headers={"x-goog-api-key": settings.gemini_api_key},
                    json={
                        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                        "contents": [{"role": "user", "parts": [{"text": _transcript_to_text(segments)}]}],
                        "generationConfig": {"responseMimeType": "application/json"},
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            # Do not persist provider response bodies, request headers, or keys.
            raise RuntimeError("Gemini transport request failed") from exc
        except ValueError as exc:
            raise ValueError("Gemini returned invalid response JSON") from exc
        try:
            candidate = data["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise ValueError("Gemini response was blocked or incomplete")
            raw = "".join(part.get("text", "") for part in candidate["content"]["parts"]
                          if not part.get("thought"))
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ValueError("Gemini returned an empty or malformed response") from exc
        return _parse_raw(raw)


def get_extractor() -> Extractor:
    """Factory: return the configured extraction backend.

    Controlled by EXTRACTOR_IMPL: transcript_only | azure_openai | mock | gemini.
    """
    if settings.extractor_impl == "transcript_only":
        return TranscriptOnlyExtractor()
    if settings.extractor_impl == "azure_openai":
        return AzureOpenAIExtractor()
    if settings.extractor_impl == "mock":
        return MockExtractor()
    if settings.extractor_impl == "gemini":
        return GeminiExtractor()
    raise ValueError(f"Unsupported EXTRACTOR_IMPL: {settings.extractor_impl}")
