"""Persist explicit calendar sync operation state; no calendar or user data rewrite."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "40c8e12a9b71"
down_revision = "2f7b9c1d4e60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calendar_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *(sa.Column(name, sa.Integer(), nullable=False)
          for name in ("succeeded", "failed", "skipped", "created", "updated")),
        sa.Column("error_category", sa.String(40), nullable=True),
        sa.CheckConstraint("active_slot IS NULL OR active_slot = 1"),
    )
    op.create_index("uq_calendar_sync_active", "calendar_sync_runs", ["active_slot"], unique=True)


def downgrade():
    op.drop_index("uq_calendar_sync_active", table_name="calendar_sync_runs")
    op.drop_table("calendar_sync_runs")
