"""add durable recording jobs

Revision ID: d6c5a2f9b104
Revises: a142cc78536e
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d6c5a2f9b104"
down_revision: Union[str, None] = "a142cc78536e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recording_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("drive_item_id", sa.String(length=255), nullable=False),
        sa.Column("drive_id", sa.String(length=255), nullable=False),
        sa.Column("owner_upn", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recording_jobs_available_at"), "recording_jobs", ["available_at"])
    op.create_index(op.f("ix_recording_jobs_drive_item_id"), "recording_jobs", ["drive_item_id"])
    op.create_index(op.f("ix_recording_jobs_owner_upn"), "recording_jobs", ["owner_upn"])
    op.create_index(op.f("ix_recording_jobs_status"), "recording_jobs", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_recording_jobs_status"), table_name="recording_jobs")
    op.drop_index(op.f("ix_recording_jobs_owner_upn"), table_name="recording_jobs")
    op.drop_index(op.f("ix_recording_jobs_drive_item_id"), table_name="recording_jobs")
    op.drop_index(op.f("ix_recording_jobs_available_at"), table_name="recording_jobs")
    op.drop_table("recording_jobs")
