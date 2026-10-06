"""Add the audit logging foundation without workflow integration."""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "b6e2a9407d13"
down_revision = "c4f8d1a2e903"
branch_labels = None
depends_on = None


def upgrade():
    # Startup create_all may already have created this exact model/table.
    if not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table("audit_events"):
        return
    op.create_table(
        "audit_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("actor_upn", sa.String(255), nullable=True),
        sa.Column("actor_entra_oid", sa.String(64), nullable=True),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("metadata", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("outcome IN ('requested', 'succeeded', 'failed', 'unknown')", name="ck_audit_events_outcome"),
        sa.CheckConstraint("actor_type IN ('user', 'system')", name="ck_audit_events_actor_type"),
        sa.UniqueConstraint("event_key", name="uq_audit_events_event_key"),
    )
    op.create_index("ix_audit_events_resource_time", "audit_events", ["resource_type", "resource_id", "occurred_at"])
    op.create_index("ix_audit_events_meeting_time", "audit_events", ["meeting_id", "occurred_at"])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])


def downgrade():
    op.drop_table("audit_events")
