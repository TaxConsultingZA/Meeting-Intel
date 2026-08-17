"""add sync and email delivery state

Revision ID: e7a91b4c2d30
Revises: d6c5a2f9b104
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7a91b4c2d30"
down_revision: Union[str, None] = "d6c5a2f9b104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Older application startup code called metadata.create_all(), so a shared
    # database may already contain this table even though Alembic has not yet
    # recorded this revision.  Inspect first so the migration safely reconciles
    # that drift instead of failing with DuplicateTableError.
    inspector = sa.inspect(op.get_bind())
    if "user_sync_states" not in inspector.get_table_names():
        op.create_table(
            "user_sync_states",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_upn", sa.String(length=255), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=20), server_default="never", nullable=False),
            sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_upn", "source", name="uq_user_sync_source"),
        )
        op.create_index("ix_user_sync_states_user_upn", "user_sync_states", ["user_upn"])

    meeting_columns = {column["name"] for column in inspector.get_columns("meetings")}
    if "email_delivery_status" not in meeting_columns:
        op.add_column("meetings", sa.Column("email_delivery_status", sa.String(20), nullable=True))
    if "email_delivery_fingerprint" not in meeting_columns:
        op.add_column("meetings", sa.Column("email_delivery_fingerprint", sa.String(64), nullable=True))
    if "email_delivery_error" not in meeting_columns:
        op.add_column("meetings", sa.Column("email_delivery_error", sa.Text(), nullable=True))
    if "email_delivery_attempts" not in meeting_columns:
        op.add_column(
            "meetings",
            sa.Column("email_delivery_attempts", sa.Integer(), server_default="0", nullable=False),
        )


def downgrade() -> None:
    op.drop_column("meetings", "email_delivery_attempts")
    op.drop_column("meetings", "email_delivery_error")
    op.drop_column("meetings", "email_delivery_fingerprint")
    op.drop_column("meetings", "email_delivery_status")
    op.drop_index("ix_user_sync_states_user_upn", table_name="user_sync_states")
    op.drop_table("user_sync_states")
