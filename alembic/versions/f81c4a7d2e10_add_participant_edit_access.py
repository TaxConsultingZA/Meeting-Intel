"""add participant edit access workflow

Revision ID: f81c4a7d2e10
Revises: e7a91b4c2d30
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f81c4a7d2e10"
down_revision: Union[str, None] = "e7a91b4c2d30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("meeting_participants")}
    if "edit_access_status" not in columns:
        op.add_column(
            "meeting_participants",
            sa.Column("edit_access_status", sa.String(20), server_default="none", nullable=False),
        )
    if "edit_requested_at" not in columns:
        op.add_column("meeting_participants", sa.Column("edit_requested_at", sa.DateTime(timezone=True)))
    if "edit_decided_at" not in columns:
        op.add_column("meeting_participants", sa.Column("edit_decided_at", sa.DateTime(timezone=True)))
    if "edit_decided_by" not in columns:
        op.add_column("meeting_participants", sa.Column("edit_decided_by", sa.String(255)))


def downgrade() -> None:
    op.drop_column("meeting_participants", "edit_decided_by")
    op.drop_column("meeting_participants", "edit_decided_at")
    op.drop_column("meeting_participants", "edit_requested_at")
    op.drop_column("meeting_participants", "edit_access_status")
