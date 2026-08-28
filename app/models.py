import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint, Boolean, Integer,
    Index, text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from .db import Base


def _uuid() -> uuid.UUID:
    """Generate a new random UUID (used as column default for primary keys)."""
    return uuid.uuid4()


def _now() -> datetime:
    """Return the current UTC datetime (used as column default for timestamps)."""
    return datetime.now(timezone.utc)


# --- Enums ---------------------------------------------------------------

class ProcessingState(str, enum.Enum):
    """All states a meeting recording can pass through in the processing pipeline.

    The happy path is: queued → downloading → transcribing → extracting →
    awaiting_review → approved → sent.  Any step can transition to ``failed``.
    """
    queued = "queued"
    downloading = "downloading"
    transcribing = "transcribing"
    extracting = "extracting"
    awaiting_review = "awaiting_review"   # the human-review gate
    approved = "approved"
    sent = "sent"
    failed = "failed"


class Confidence(str, enum.Enum):
    """Confidence level the extractor assigns to each action item it identified."""
    high = "high"
    medium = "medium"
    low = "low"


# --- Registration --------------------------------------------------------

BUSINESS_UNITS = [
    "Tax Technical",
    "xpatweb",
    "Financial Emigration",
    "CPD Consortium",
    "Marketing",
    "IT and Devs",
]


class BusinessUnit(Base):
    """A business unit within Taxconsulting SA.

    Pre-seeded at startup from ``BUSINESS_UNITS``.  Users are assigned to one BU
    when they are registered, grouping their activity for organisational purposes.
    """
    __tablename__ = "business_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    users: Mapped[list["RegisteredUser"]] = relationship(back_populates="business_unit")


class RegisteredUser(Base):
    """A domain user explicitly registered to use the Meeting Intelligence platform.

    Registration permits sign-in; only users with ``is_subscribed=True`` have
    Calendar/OneDrive data scanned and processed.
    Admin users (``is_admin=True``) can access the ``/admin`` management panel.
    The first admin UPN(s) are bootstrapped from the ``ADMIN_UPNS`` env var at startup.
    """
    __tablename__ = "registered_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    upn: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    entra_oid: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_unit_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("business_units.id"), nullable=True
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_subscribed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    subscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    graph_drive_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    business_unit: Mapped["BusinessUnit | None"] = relationship(back_populates="users")


class UserSyncState(Base):
    """Last known Microsoft sync result for one user and one data source.

    Keeping failures in PostgreSQL prevents a Graph permission or network error
    from being presented to the user as a legitimate empty calendar/OneDrive.
    """
    __tablename__ = "user_sync_states"
    __table_args__ = (UniqueConstraint("user_upn", "source", name="uq_user_sync_source"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_upn: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="never", server_default="never", nullable=False
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


# --- Dedupe ledger -------------------------------------------------------
# Both the webhook AND the reconciliation worker funnel through this.
# Idempotency key = Graph drive item id. If a row exists, we skip.

class ProcessedItem(Base):
    """Deduplication ledger — one row per OneDrive drive item id ever seen.

    Both the Graph webhook handler and the reconcile worker insert here before
    processing.  If a row already exists, the item is skipped.  This prevents
    double-processing when a webhook fires and the reconcile cron runs close together.
    """
    __tablename__ = "processed_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    drive_item_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    drive_id: Mapped[str | None] = mapped_column(String(255), nullable=True)   # whose OneDrive
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(32))  # "webhook" | "reconcile"
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RecordingJob(Base):
    """Durable recording-processing job stored in PostgreSQL.

    The API only enqueues work.  A separate worker claims pending rows with
    ``FOR UPDATE SKIP LOCKED`` so Railway restarts cannot silently discard an
    in-flight recording as happened with in-process ``asyncio.create_task``.
    """
    __tablename__ = "recording_jobs"
    __table_args__ = (
        Index("uq_recording_jobs_active_item", "drive_item_id", unique=True,
              postgresql_where=text("status IN ('pending', 'processing')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    drive_item_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    drive_id: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_upn: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", index=True, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class SyncedCalendarEvent(Base):
    """Cached Outlook event for an opted-in user.

    This makes calendar discovery a real background sync rather than a page-load
    side effect. The raw Graph shape is retained so the UI can evolve without
    repeatedly re-fetching old events.
    """
    __tablename__ = "synced_calendar_events"
    __table_args__ = (UniqueConstraint("user_upn", "event_id", name="uq_calendar_user_event"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_upn: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --- Core domain ---------------------------------------------------------

class Meeting(Base):
    """Core domain model representing a single recorded meeting.

    Tracks the full lifecycle from raw recording through AI processing to the
    final approved notes email.  The ``extracted_json`` JSONB column stores the
    complete structured output returned by the extractor (speaker highlights,
    discussion points, action items, etc.).
    """
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    drive_item_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    organizer_upn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[ProcessingState] = mapped_column(
        SAEnum(ProcessingState), default=ProcessingState.queued, index=True
    )
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Full attendee UPN list captured at processing time — used to auto-grant
    # historical access when a user registers after a meeting was already processed.
    attendees_raw: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_recipients: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Durable send state.  ``sending`` deliberately blocks automatic retries
    # after a process crash because the external Graph outcome is then unknown;
    # this is safer than emailing attendees twice.
    email_delivery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email_delivery_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_delivery_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    action_items: Mapped[list["ActionItem"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    # Row-level access: who is allowed to see this meeting's outputs.
    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class MeetingParticipant(Base):
    """Authorization is row-level: a user sees a meeting only if they appear here.
    A tax discussion between two partners must NOT surface in a third employee's
    dashboard.

    ``access_type`` records how the row was created:
    - ``participant``: normal pipeline flow (was an attendee when processed)
    - ``shared``: meeting owner explicitly shared the transcript with this person
    - ``historical``: user registered after the meeting was processed and requested access
    """
    __tablename__ = "meeting_participants"
    __table_args__ = (UniqueConstraint("meeting_id", "user_upn", name="uq_meeting_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    user_upn: Mapped[str] = mapped_column(String(255), index=True)
    is_organizer: Mapped[bool] = mapped_column(Boolean, default=False)
    access_type: Mapped[str] = mapped_column(String(20), default="participant", server_default="participant")
    # View access and edit access are deliberately separate.  Attendees may
    # ask the organiser for edit access without gaining approval/email rights.
    edit_access_status: Mapped[str] = mapped_column(
        String(20), default="none", server_default="none", nullable=False
    )
    edit_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edit_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edit_decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")


class MeetingEmailAudit(Base):
    """Immutable-attribution log for participant self-copy delivery attempts."""
    __tablename__ = "meeting_email_audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    actor_upn: Mapped[str] = mapped_column(String(255), index=True)
    recipient_upn: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(32), default="self_copy", server_default="self_copy")
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ActionItem(Base):
    """A single action item extracted from a meeting transcript.

    Items start as ``approved=False`` and are gated behind the organiser's
    review — nothing is emailed until the organiser approves them.  The
    ``raw`` JSONB column preserves the original extractor output for debugging.
    """
    __tablename__ = "action_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id"), index=True)

    task: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deadline_text: Mapped[str | None] = mapped_column(String(255), nullable=True)  # "early June" as-said
    deadline_iso: Mapped[str | None] = mapped_column(String(32), nullable=True)    # only if confident
    confidence: Mapped[Confidence] = mapped_column(SAEnum(Confidence), default=Confidence.medium)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)          # grounding

    # Review gate: nothing emails until an org member approves/edits.
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    meeting: Mapped["Meeting"] = relationship(back_populates="action_items")
