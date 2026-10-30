"""Fail-closed admission and durable one-submission ledger. Never backfill grants."""
from alembic import op
import sqlalchemy as sa
revision = "92d6a10f4e72"
down_revision = "51d8f2a7c903"
branch_labels = None
depends_on = None

def upgrade():
    for column in (
        sa.Column("admission_version", sa.Integer(), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorized_by", sa.String(255), nullable=True),
        sa.Column("submission_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_status", sa.String(32), nullable=True),
        sa.Column("provider_transcript_id", sa.String(255), nullable=True),
        sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
        sa.Column("detected_language", sa.String(32), nullable=True),
    ):
        op.add_column("recording_jobs", column)

def downgrade():
    for name in ("detected_language", "audio_duration_seconds", "provider_transcript_id",
                 "provider_status", "submission_count", "authorized_by", "authorized_at", "admission_version"):
        op.drop_column("recording_jobs", name)
