"""add opt-in, calendar cache and approval audit

Revision ID: 8c2f7a41d930
Revises: 45b4fd14ee56
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8c2f7a41d930"
down_revision: Union[str, None] = "45b4fd14ee56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "registered_users",
        sa.Column("is_subscribed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "registered_users",
        sa.Column("subscribed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "meetings",
        sa.Column("approved_recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("meetings", sa.Column("approved_by", sa.String(length=255), nullable=True))
    op.add_column(
        "meetings",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "synced_calendar_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_upn", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_upn", "event_id", name="uq_calendar_user_event"),
    )
    op.create_index(
        op.f("ix_synced_calendar_events_user_upn"),
        "synced_calendar_events",
        ["user_upn"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_synced_calendar_events_user_upn"),
        table_name="synced_calendar_events",
    )
    op.drop_table("synced_calendar_events")
    op.drop_column("meetings", "approved_at")
    op.drop_column("meetings", "approved_by")
    op.drop_column("meetings", "approved_recipients")
    op.drop_column("registered_users", "subscribed_at")
    op.drop_column("registered_users", "is_subscribed")
