"""Owner-approved cross-user recording requests."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "ae52c790b316"
down_revision = "8e31a4c2d907"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recording_processing_requests",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("requester_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("registered_users.id"), nullable=False),
        sa.Column("recording_owner_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("registered_users.id"), nullable=False),
        sa.Column("event_id", sa.String(512), nullable=False),
        sa.Column("occurrence_key", sa.String(64), nullable=False),
        sa.Column("event_snapshot", pg.JSONB(), nullable=False),
        sa.Column("drive_id", sa.String(255), nullable=False),
        sa.Column("drive_item_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", pg.UUID(as_uuid=True), sa.ForeignKey("registered_users.id")),
        sa.Column("job_id", pg.UUID(as_uuid=True), sa.ForeignKey("recording_jobs.id")),
        sa.Column("meeting_id", pg.UUID(as_uuid=True), sa.ForeignKey("meetings.id")),
        sa.CheckConstraint("status IN ('pending', 'approved', 'denied')", name="ck_processing_request_status"),
    )
    for column in ("requester_user_id", "recording_owner_user_id", "occurrence_key", "drive_item_id"):
        op.create_index(f"ix_recording_processing_requests_{column}", "recording_processing_requests", [column])
    op.create_index("uq_processing_request_pending", "recording_processing_requests",
                    ["requester_user_id", "occurrence_key"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))


def downgrade():
    op.drop_table("recording_processing_requests")
