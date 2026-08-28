from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from .models import Confidence, ProcessingState


# ── Registration schemas ──────────────────────────────────────────────────────

class BusinessUnitOut(BaseModel):
    """API response shape for a business unit."""
    id: int
    name: str


class RegisteredUserOut(BaseModel):
    """API response shape for a registered platform user."""
    upn: str
    display_name: str | None
    business_unit_id: int | None
    business_unit_name: str | None
    is_admin: bool
    is_subscribed: bool
    subscribed_at: str | None
    registered_at: str


class RegisterUserIn(BaseModel):
    """Payload for POST /admin/users — register a new platform user."""
    upn: str
    display_name: str | None = None
    business_unit_id: int | None = None
    is_admin: bool = False

    @field_validator("upn")
    @classmethod
    def must_be_taxconsulting(cls, v: str) -> str:
        if not v.lower().endswith("@taxconsulting.co.za"):
            raise ValueError("UPN must be a @taxconsulting.co.za address")
        return v.lower()


class UpdateUserIn(BaseModel):
    """Payload for PATCH /admin/users/{upn} — update registration details."""
    display_name: str | None = None
    business_unit_id: int | None = None
    is_admin: bool | None = None


class SubscriptionOut(BaseModel):
    is_subscribed: bool
    subscribed_at: str | None


class SyncStateOut(BaseModel):
    source: str
    status: str
    last_attempted_at: str | None
    last_succeeded_at: str | None
    last_error: str | None


class ShareMeetingIn(BaseModel):
    """Payload for POST /reviews/{id}/share — share a transcript with a colleague."""
    recipient_upn: str

    @field_validator("recipient_upn")
    @classmethod
    def must_be_taxconsulting(cls, v: str) -> str:
        if not v.lower().endswith("@taxconsulting.co.za"):
            raise ValueError("Can only share with @taxconsulting.co.za addresses")
        return v.lower()


# ── API output models ─────────────────────────────────────────────────────────

class ActionItemOut(BaseModel):
    """API response shape for a single action item returned to the frontend."""
    id: str
    task: str
    owner: str | None
    deadline_text: str | None
    deadline_iso: str | None
    confidence: Confidence
    source_quote: str | None
    approved: bool


class ActionItemEdit(BaseModel):
    """Partial-update payload accepted by PATCH /reviews/action-items/{id}.

    All fields are optional — only the provided keys are written to the DB.
    """
    task: str | None = None
    owner: str | None = None
    deadline_iso: str | None = None
    confidence: Confidence | None = None


class TranscriptEdit(BaseModel):
    transcript: str


class SpeakerMappingIn(BaseModel):
    mappings: dict[str, str | None]


class EditAccessDecisionIn(BaseModel):
    approved: bool


class EditAccessRequestOut(BaseModel):
    requester_upn: str
    status: str
    requested_at: datetime | None = None


class MeetingOut(BaseModel):
    """Full meeting representation returned by GET /reviews and GET /reviews/{id}."""
    id: str
    recorded_at: datetime | None = None
    title: str | None
    state: ProcessingState
    summary: str | None
    transcript: str | None = None
    organizer_upn: str | None = None
    extracted_json: dict | None = None
    error: str | None = None
    email_recipients: list[str] = Field(default_factory=list)
    approved_recipients: list[str] = Field(default_factory=list)
    is_organizer: bool = False
    can_edit: bool = False
    can_request_edit_access: bool = False
    edit_access_status: str = "none"
    edit_access_requests: list[EditAccessRequestOut] = Field(default_factory=list)
    speaker_candidates: list[str] = Field(default_factory=list)
    speaker_mappings: dict[str, str | None] = Field(default_factory=dict)
    speaker_sample_labels: list[str] = Field(default_factory=list)
    action_items: list[ActionItemOut]


class EmailPreviewOut(BaseModel):
    subject: str
    html: str


class ApproveMeetingIn(BaseModel):
    recipients: list[str] = []

    @field_validator("recipients")
    @classmethod
    def normalise_recipients(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(v.strip().lower() for v in values if v.strip()))


class SendMeetingCopyIn(BaseModel):
    recipient_upn: str

    @field_validator("recipient_upn")
    @classmethod
    def normalise_recipient(cls, value: str) -> str:
        return value.strip().lower()


# ── Optional rich extraction schema ───────────────────────────────────────────

class ExtractedActionItem(BaseModel):
    """Action item as returned by the AI extractor.

    Carries both the new field names (``action``, ``assigned_to``, ``due_date``)
    and legacy aliases (``task``, ``owner``, ``deadline_text``) so that older
    DB records serialise correctly.  ``model_post_init`` keeps them in sync.
    """
    action: str
    assigned_to: str | None = None
    department: str | None = None
    reason: str | None = None
    expected_outcome: str | None = None
    due_date: str | None = None
    # kept for DB compatibility
    task: str | None = None
    owner: str | None = None
    deadline_text: str | None = None
    deadline_iso: str | None = None
    confidence: Confidence = Confidence.medium
    source_quote: str | None = None

    def model_post_init(self, __context):
        # keep legacy fields in sync so existing DB writes still work
        if not self.task:
            self.task = self.action
        if not self.owner:
            self.owner = self.assigned_to
        if not self.deadline_text:
            self.deadline_text = self.due_date


class DiscussionPoint(BaseModel):
    topic: str
    summary: str
    outcome: str | None = None


class Deliverable(BaseModel):
    deliverable: str
    responsible: str | None = None
    delivery_method: str | None = None
    due_date: str | None = None
    expected_outcome: str | None = None


class Risk(BaseModel):
    item: str
    impact: str | None = None
    resolution: str | None = None
    owner: str | None = None


class NextMeeting(BaseModel):
    proposed_date: str | None = None
    proposed_time: str | None = None
    agenda_focus: str | None = None


class SpeakerHighlight(BaseModel):
    speaker: str
    role: str | None = None          # inferred role if identifiable (e.g. "Facilitator")
    key_points: list[str] = []       # most important things this speaker said


class RichExtractionResult(BaseModel):
    """Complete structured output produced by the AI extractor for one meeting.

    This is serialised as-is into the ``Meeting.extracted_json`` JSONB column
    and later read by both the review UI and the email template builder.
    """
    extraction_mode: str = "structured"
    objective: str = ""
    attendees: list[str] = []
    apologies: list[str] = []
    platform: str = "Microsoft Teams"
    meeting_time: str | None = None
    speaker_highlights: list[SpeakerHighlight] = []
    discussion_points: list[DiscussionPoint] = []
    action_items: list[ExtractedActionItem] = []
    deliverables: list[Deliverable] = []
    risks: list[Risk] = []
    next_steps: list[str] = []
    next_meeting: NextMeeting | None = None
    # kept for backwards compat
    summary: str = ""
