"""add meeting email audit records

Revision ID: 3f7a2b61c9d4
Revises: f81c4a7d2e10
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "3f7a2b61c9d4"
down_revision: Union[str, None] = "f81c4a7d2e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "meeting_email_audits" not in inspector.get_table_names():
        op.create_table(
            "meeting_email_audits",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("actor_upn", sa.String(length=255), nullable=False),
            sa.Column("recipient_upn", sa.String(length=255), nullable=False),
            sa.Column("action", sa.String(length=32), server_default="self_copy", nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_meeting_email_audits_meeting_id", "meeting_email_audits", ["meeting_id"])
        op.create_index("ix_meeting_email_audits_actor_upn", "meeting_email_audits", ["actor_upn"])


def downgrade() -> None:
    op.drop_index("ix_meeting_email_audits_actor_upn", table_name="meeting_email_audits")
    op.drop_index("ix_meeting_email_audits_meeting_id", table_name="meeting_email_audits")
    op.drop_table("meeting_email_audits")
