"""bind subscribers to their OneDrive

Revision ID: 9d331bf017aa
Revises: 8c2f7a41d930
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d331bf017aa"
down_revision: Union[str, None] = "8c2f7a41d930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "registered_users",
        sa.Column("graph_drive_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_registered_users_graph_drive_id"),
        "registered_users",
        ["graph_drive_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_registered_users_graph_drive_id"),
        table_name="registered_users",
    )
    op.drop_column("registered_users", "graph_drive_id")
